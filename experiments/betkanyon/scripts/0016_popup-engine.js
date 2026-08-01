var PopupEngineModule = PopupEngineModule || (function () {
    var POPUP_STORAGE_KEYS = {
        CONFIG: 'popup:config',
        ANNOUNCEMENTS_HIDDEN_UNTIL: 'announcements_hidden_until',
        ANNOUNCEMENTS_IDS: 'announcements_hidden_until',
        AREA_SETTINGS: 'area_settings',
        ANNOUNCEMENTS: 'announcements',
        ANNOUNCEMENT_CONTENTS: 'announcement_contents',
        HIDDEN_ANNOUNCEMENTS: 'hidden_announcements'
    };

    var POPUP_STORAGE_TTL = {
        CONFIG_MS: 15 * 60 * 1000,
        AFTER_CLOSE_DELAY_MS: 2 * 1000,
        INITIAL_DELAY_MS: 2 * 1000
    };

    var POPUP_DISPLAY_OPTIONS = {
        OPEN_SITE: 1,
        AFTER_LOGIN: 2,
        AFTER_REGISTRATION: 3,
        BIRTHDAY: 4,
        VISIT_PAGE: 5,
        PLAYER_VERIFICATION: 6
    };

    var POPUP_URL_MATCH_TYPE = {
        EQUALS: 1,
        STARTS_WITH: 2,
        CONTAINS: 3
    };

    var SLIDER_ANIMATION_TYPE = {
        HORIZONTAL: 1,
        FADED: 2,
    };

    var ANIMATION_SPEED = {
        Slow: 1,
        Normal: 2,
        Fast: 3,
    };

    var FADED_ANIMATION_OPTIONS = {
        Slow: {
            VisibleTime: 8,
            FadeDuration: 800
        },
        Normal: {
            VisibleTime: 5,
            FadeDuration: 500
        },
        Fast: {
            VisibleTime: 3,
            FadeDuration: 300
        },
    }

    var HORIZONTAL_ANIMATION_OPTIONS = {
        Slow: {
            PixelsPerSecond: 40
        },
        Normal: {
            PixelsPerSecond: 70
        },
        Fast: {
            PixelsPerSecond: 110
        }
    }

    var state = {
        context: {
            playerId: 0,
            language: '',
            currencyCode: '',
            previewPopupId: 0,
            cookieDomain: '',
            baseUrl: '',
            isMobile: false,
        },
        timerId: null,
        rafId: null,

        announcementViewportObserver: null,
        announcementViewportResizeHandler: null,
        isContentHovered: false,

        queue: [],
        announcementsQueue: [],
        announcementValidIds: [],
        activePopup: null,
        playerPopupViews: [],
        eventsBound: false,
        timerId: null,
        areaSettings: {
            Id: 0,
            PartnerId: 0,
            SliderAnimationType: SLIDER_ANIMATION_TYPE.HORIZONTAL,
            AnimationSpeed: ANIMATION_SPEED.Normal,
            IsAutoplayOn: true,
            IsMakeAnnouncementPermanentOn: true,
            BackgroundColor: null,
            TextColor: null,
            IsBlockIconOn: true,
            BlockIcon: null
        },
        validSlidesCount: 0,
        mobileHorizontalClicked: false
    };

    var currentRunCallId = 0;

    function init(args) {

        $.extend(state.context, args || {});

        state.context.playerId = Number(state.context.playerId) || 0;
        state.context.baseUrl = String(state.context.baseUrl || '')
        state.context.language = getDocumentLanguage();
        state.context.currencyCode = String(state.context.currencyCode || '').toUpperCase();
        state.context.previewPopupId = Number(state.context.previewPopupId) || 0;
        state.context.cookieDomain = String(state.context.cookieDomain || '');
        state.context.isMobile = Boolean(state.context.isMobile || false);
    }

    function getDocumentLanguage() {
        var lang = String(document.documentElement.lang || '').toLowerCase();

        if (!lang) {
            return '';
        }

        return lang.split('-')[0];
    }
    function parseDotNetDate(value) {
        if (!value) {
            return null;
        }

        if (typeof value === 'number') {
            return value;
        }

        if (value instanceof Date) {
            return value.getTime();
        }

        if (typeof value === 'string') {
            var dotNetMatch = /\/Date\((\d+)\)\//.exec(value);

            if (dotNetMatch) {
                return Number(dotNetMatch[1]);
            }

            var parsed = new Date(value).getTime();
            return Number.isNaN(parsed) ? null : parsed;
        }

        return null;
    }

    function normalizeFields(data) {
        return $.extend({}, data, {
            StartDateTs: parseDotNetDate(data.StartDate),
            EndDateTs: parseDotNetDate(data.EndDate)
        });
    }

    function normalizeData(data) {
        return Array.isArray(data) ? data.map(normalizeFields) : [];
    }

    function normalizePlayerPopupViews(items) {
        if (!Array.isArray(items)) {
            return [];
        }

        return items.map(function (item) {
            return $.extend({}, item, {
                PopupId: Number(item.PopupId != null ? item.PopupId : item.Id),
                LastSeenDateTs:
                    Number(item.LastSeenDateTs || 0) || parseDotNetDate(item.LastSeenDate)
            });
        });
    }

    function getCurrentPlayerId() {
        return state.context.playerId;
    }

    function isLoggedInPopupViewer() {
        return getCurrentPlayerId() > 0;
    }

    function getCurrentPopupViewerKey() {
        var playerId = getCurrentPlayerId();
        return playerId > 0 ? 'player:' + playerId : 'guest';
    }

    function getCurrentPath() {
        return normalizeUrlForPopupMatch(
            window.location.pathname + window.location.search
        );
    }

    function getStoredPopupConfig() {
        var raw = localStorage.getItem(POPUP_STORAGE_KEYS.CONFIG);

        if (!raw) {
            return null;
        }

        try {
            var payload = JSON.parse(raw);

            if (!payload || !payload.expiresAt || Date.now() > payload.expiresAt) {
                localStorage.removeItem(POPUP_STORAGE_KEYS.CONFIG);
                return null;
            }

            return normalizeData(Array.isArray(payload.data) ? payload.data : []);
        } catch (e) {
            localStorage.removeItem(POPUP_STORAGE_KEYS.CONFIG);
            return null;
        }
    }

    function savePopupConfig(popups) {
        var payload = {
            data: normalizeData(popups),
            savedAt: Date.now(),
            expiresAt: Date.now() + POPUP_STORAGE_TTL.CONFIG_MS
        };

        localStorage.setItem(POPUP_STORAGE_KEYS.CONFIG, JSON.stringify(payload));
    }

    function removePopupFromStorage(popupId) {
        var storedPopups = getStoredPopupConfig() || [];
        var updatedPopups = storedPopups.filter(function (popup) {
            return popup.Id !== popupId;
        });

        savePopupConfig(updatedPopups);
    }

    function getDismissStorageKey(popupId) {
        return 'popup:dismissed:' + getCurrentPopupViewerKey() + ':' + popupId;
    }

    function getLastShownStorageKey(popupId) {
        return 'popup:lastShownAt:' + getCurrentPopupViewerKey() + ':' + popupId;
    }

    function markPopupDismissedLocal(popupId) {
        localStorage.setItem(getDismissStorageKey(popupId), '1');
    }

    function isPopupDismissedLocal(popupId) {
        return localStorage.getItem(getDismissStorageKey(popupId)) === '1';
    }

    function markPopupShownLocal(popupId, time) {
        localStorage.setItem(getLastShownStorageKey(popupId), String(time || Date.now()));
    }

    function getPopupLastShownLocal(popupId) {
        var raw = localStorage.getItem(getLastShownStorageKey(popupId));
        return raw ? Number(raw) : null;
    }

    function clearAllPopupConfigCache() {
        var keysToRemove = [];

        for (var i = 0; i < localStorage.length; i += 1) {
            var key = localStorage.key(i);

            if (key && key.indexOf(POPUP_STORAGE_KEYS.CONFIG) === 0) {
                keysToRemove.push(key);
            }
        }

        keysToRemove.forEach(function (key) {
            localStorage.removeItem(key);
        });
    }

    function getPlayerPopupViewsCookieKey(playerId) {
        return 'popup_views_player_' + (Number(playerId) || 0);
    }

    function getPopupConfigResetCookieKey() {
        return 'popup_reset_config';
    }

    function isBirthdayTriggerOn(playerId) {
        return getCookie('popup_birthday_player_' + (Number(playerId) || 0)) === '1';
    }

    function isLoginTriggerOn(playerId) {
        return getCookie('popup_login_player_' + (Number(playerId) || 0)) === '1';
    }

    function isRegistrationTriggerOn(playerId) {
        return getCookie('popup_registration_player_' + (Number(playerId) || 0)) === '1';
    }

    function consumeLoginTrigger(playerId) {
        setCookie(
            'popup_login_player_' + (Number(playerId) || 0),
            '0',
            2,
            state.context.cookieDomain
        );
    }

    function consumeRegistrationTrigger(playerId) {
        setCookie(
            'popup_registration_player_' + (Number(playerId) || 0),
            '0',
            2,
            state.context.cookieDomain
        );
    }

    function shouldResetPopupConfig() {
        return getCookie(getPopupConfigResetCookieKey()) === '1';
    }

    function consumePopupConfigReset() {
        if (!shouldResetPopupConfig()) {
            return;
        }

        clearAllPopupConfigCache();

        setCookie(
            getPopupConfigResetCookieKey(),
            '0',
            2,
            state.context.cookieDomain
        );
    }

    function getPlayerPopupViewsFromCookie(playerId) {
        if (!(Number(playerId) > 0)) {
            return [];
        }

        var raw = getCookie(getPlayerPopupViewsCookieKey(playerId));

        if (!raw || raw === 'null') {
            return [];
        }

        try {
            var parsed = JSON.parse(raw);
            return Array.isArray(parsed) ? parsed : [];
        } catch (e) {
            return [];
        }
    }

    function savePlayerPopupViewsToCookie(playerId, views) {
        if (!(Number(playerId) > 0)) {
            return;
        }

        var normalized = (Array.isArray(views) ? views : []).map(function (item) {
            return {
                PopupId: Number(item.PopupId != null ? item.PopupId : item.Id),
                LastSeenDateTs: Number(item.LastSeenDateTs || Date.now()),
                IsDismissed: !!item.IsDismissed
            };
        });

        setCookie(
            getPlayerPopupViewsCookieKey(playerId),
            JSON.stringify(normalized),
            2,
            state.context.cookieDomain
        );
    }

    function loadPlayerPopupViewsFromCookie(playerId) {
        state.playerPopupViews = normalizePlayerPopupViews(getPlayerPopupViewsFromCookie(playerId));
    }

    function getPlayerPopupViewById(popupId) {
        for (var i = 0; i < state.playerPopupViews.length; i += 1) {
            var item = state.playerPopupViews[i];

            if (Number(item.PopupId != null ? item.PopupId : item.Id) === Number(popupId)) {
                return item;
            }
        }

        return null;
    }

    function getPopupLastShownCookie(popupId) {
        var item = getPlayerPopupViewById(popupId);
        return item ? item.LastSeenDateTs : null;
    }

    function isPopupDismissedCookie(popupId) {
        var item = getPlayerPopupViewById(popupId);
        return !!(item && item.IsDismissed);
    }

    function upsertPlayerPopupViewCookie(popupId, isDismissed) {
        var playerId = getCurrentPlayerId();

        if (!(playerId > 0)) {
            return;
        }

        var rawViews = getPlayerPopupViewsFromCookie(playerId) || [];
        var now = Date.now();
        var existingIndex = -1;

        for (var i = 0; i < rawViews.length; i += 1) {
            var item = rawViews[i];
            if (Number(item.PopupId != null ? item.PopupId : item.Id) === Number(popupId)) {
                existingIndex = i;
                break;
            }
        }

        var updatedItem = {
            PopupId: Number(popupId),
            LastSeenDateTs: now,
            IsDismissed: !!isDismissed
        };

        if (existingIndex >= 0) {
            rawViews[existingIndex] = $.extend({}, rawViews[existingIndex], updatedItem);
        } else {
            rawViews.push(updatedItem);
        }

        savePlayerPopupViewsToCookie(playerId, rawViews);
        state.playerPopupViews = normalizePlayerPopupViews(rawViews);
    }

    async function fetchBrandAnnouncements() {
        var response = await fetch('/DynamicPopUp/BrandAnnouncements', {
            method: 'GET',
            credentials: 'include'
        });

        var result = null;

        try {
            result = await response.json();
        } catch (e) {
            throw new Error('Failed to fetch brand announcements');
        }

        if (!result || !result.Success) {
            throw new Error((result && result.Message) || 'Failed to fetch brand announcements');
        }

        return Array.isArray(result.Data) ? result.Data : [];
    }

    async function fetchBrandPopups() {
        var response = await fetch('/DynamicPopUp/BrandPopups', {
            method: 'GET',
            credentials: 'include'
        });

        var result = null;

        try {
            result = await response.json();
        } catch (e) {
            throw new Error('Failed to fetch brand popups');
        }

        if (!result || !result.Success) {
            throw new Error((result && result.Message) || 'Failed to fetch brand popups');
        }

        return Array.isArray(result.Data) ? result.Data : [];
    }

    async function fetchBrandAreaSettings() {
        var response = await fetch('/DynamicPopUp/GetAreaSettings', { method: 'GET', credentials: 'include' });
        var result = null;
        try { result = await response.json(); } catch (e) { throw new Error('Failed to fetch settings'); }
        if (!result || !result.Success) throw new Error((result && result.Message) || 'Failed to fetch settings');
        return result.Data;
    }

    async function loadPopupConfig() {
        var storedPopups = getStoredPopupConfig();

        if (storedPopups !== null) {
            return storedPopups;
        }

        var popups = await fetchBrandPopups();
        savePopupConfig(popups);

        return normalizeData(popups);
    }

    async function fetchPopupContent(popupId) {
        var response = await fetch('/DynamicPopUp/PopupContent', {
            method: 'POST',
            credentials: 'include',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
            },
            body: new URLSearchParams({ id: popupId }).toString()
        });

        var contentType = String(response.headers.get('content-type') || '').toLowerCase();

        if (contentType.indexOf('application/json') >= 0) {
            try {
                await response.json();
            } catch (e) {
            }

            return null;
        }

        var html = await response.text();
        return html && html.trim() ? html : null;
    }

    async function savePopupSeenStatus(popupId, isDismissed) {
        var response = await fetch('/DynamicPopUp/SavePopupSeenStatus', {
            method: 'POST',
            credentials: 'include',
            headers: {
                'Content-Type': 'application/json; charset=UTF-8'
            },
            body: JSON.stringify({
                PopupId: popupId,
                IsDismissed: isDismissed
            })
        });

        var result = null;

        try {
            result = await response.json();
        } catch (e) {
            return false;
        }

        return !!(result && result.Success);
    }
    function isLanguagePathSegment(segment) {
        segment = String(segment || '').toLowerCase();

        if (!segment) {
            return false;
        }

        var currentLanguage = String(state.context.language || '').toLowerCase();

        return segment === currentLanguage ||
            segment.indexOf(currentLanguage + '-') === 0;
    }

    function normalizeUrlForPopupMatch(value) {
        if (!value) {
            return '';
        }

        var url = String(value).toLowerCase().trim();

        // If popup.Url is full URL, take only path + query
        if (/^[a-z][a-z0-9+.-]*:\/\//i.test(url)) {
            var parser = document.createElement('a');
            parser.href = url;
            url = parser.pathname + parser.search;
        }

        if (url.charAt(0) !== '/') {
            url = '/' + url;
        }

        var queryIndex = url.indexOf('?');
        var path = queryIndex >= 0 ? url.substring(0, queryIndex) : url;
        var query = queryIndex >= 0 ? url.substring(queryIndex) : '';

        var parts = path.split('/'); // "/en/home" => ["", "en", "home"]

        if (parts.length > 2 && isLanguagePathSegment(parts[1])) {
            parts.splice(1, 1); // remove language
            path = parts.join('/') || '/';
        }

        return path + query;
    }
    function matchesUrl(popup, currentUrl) {
        var popupUrl = popup.Url
            ? normalizeUrlForPopupMatch(popup.Url)
            : null;

        currentUrl = normalizeUrlForPopupMatch(currentUrl);

        if (!popupUrl) {
            return true;
        }

        switch (popup.UrlMatchType) {
            case POPUP_URL_MATCH_TYPE.EQUALS:
                return currentUrl === popupUrl;

            case POPUP_URL_MATCH_TYPE.STARTS_WITH:
                return currentUrl.indexOf(popupUrl) === 0;

            case POPUP_URL_MATCH_TYPE.CONTAINS:
                return currentUrl.indexOf(popupUrl) >= 0;

            default:
                return true;
        }
    }
    function matchesLanguage(popup) {
        if (!Array.isArray(popup.Languages) || popup.Languages.length === 0) {
            return true;
        }

        var currentLanguage = state.context.language;

        return popup.Languages.some(function (language) {
            return String(language).toLowerCase() === currentLanguage;
        });
    }

    function matchesCurrency(popup) {
        if (!Array.isArray(popup.Currencies) || popup.Currencies.length === 0) {
            return true;
        }

        var currentCurrency = state.context.currencyCode;

        return popup.Currencies.some(function (currency) {
            return String(currency).toUpperCase() === currentCurrency;
        });
    }

    function isPopupActive(popup) {
        var now = Date.now();

        if (popup.StartDateTs && now < popup.StartDateTs) {
            return false;
        }

        if (popup.EndDateTs && now > popup.EndDateTs) {
            return false;
        }

        return true;
    }

    function getPopupCooldownMs(popup) {
        var hours = Number(popup.ReopenFrequency || 0);
        return hours > 0 ? hours * 60 * 60 * 1000 : 0;
    }

    function getPopupLastShownEffective(popupId) {
        return isLoggedInPopupViewer()
            ? getPopupLastShownCookie(popupId)
            : getPopupLastShownLocal(popupId);
    }

    function isPopupDismissedEffective(popupId) {
        return isLoggedInPopupViewer()
            ? isPopupDismissedCookie(popupId)
            : isPopupDismissedLocal(popupId);
    }

    function canShowPopupByFrequency(popup) {
        if (
            popup.DisplayOptions === POPUP_DISPLAY_OPTIONS.AFTER_REGISTRATION &&
            isRegistrationTriggerOn(getCurrentPlayerId())
        ) {
            return true;
        }

        if (
            popup.ReopenFrequency === null ||
            popup.ReopenFrequency === undefined ||
            popup.ReopenFrequency === ''
        ) {
            return true;
        }

        var lastShownAt = getPopupLastShownEffective(popup.Id);
        var reopenFrequency = Number(popup.ReopenFrequency || 0);

        if (!lastShownAt) {
            return true;
        }

        if (reopenFrequency === 0) {
            return false;
        }

        return Date.now() - lastShownAt >= getPopupCooldownMs(popup);
    }

    function getInitialTriggers(popups) {
        var triggers = [];
        var currentUrl = getCurrentPath();
        var playerId = getCurrentPlayerId();

        var hasOpenSitePopup = popups.some(function (popup) {
            return popup.DisplayOptions === POPUP_DISPLAY_OPTIONS.OPEN_SITE &&
                isPopupActive(popup) &&
                matchesLanguage(popup) &&
                matchesCurrency(popup);
        });

        var hasVisitPagePopup = popups.some(function (popup) {
            return popup.DisplayOptions === POPUP_DISPLAY_OPTIONS.VISIT_PAGE &&
                isPopupActive(popup) &&
                matchesLanguage(popup) &&
                matchesCurrency(popup) &&
                matchesUrl(popup, currentUrl);
        });

        var hasBirthdayPopup = isBirthdayTriggerOn(playerId) && popups.some(function (popup) {
            return popup.DisplayOptions === POPUP_DISPLAY_OPTIONS.BIRTHDAY &&
                isPopupActive(popup) &&
                matchesLanguage(popup) &&
                matchesCurrency(popup);
        });

        var hasLoginPopup = isLoginTriggerOn(playerId) && popups.some(function (popup) {
            return popup.DisplayOptions === POPUP_DISPLAY_OPTIONS.AFTER_LOGIN &&
                isPopupActive(popup) &&
                matchesLanguage(popup) &&
                matchesCurrency(popup);
        });

        var hasRegistrationPopup = isRegistrationTriggerOn(playerId) && popups.some(function (popup) {
            return popup.DisplayOptions === POPUP_DISPLAY_OPTIONS.AFTER_REGISTRATION &&
                isPopupActive(popup) &&
                matchesLanguage(popup) &&
                matchesCurrency(popup);
        });

        if (hasOpenSitePopup) {
            triggers.push(POPUP_DISPLAY_OPTIONS.OPEN_SITE);
        }

        if (hasVisitPagePopup) {
            triggers.push(POPUP_DISPLAY_OPTIONS.VISIT_PAGE);
        }

        if (hasBirthdayPopup) {
            triggers.push(POPUP_DISPLAY_OPTIONS.BIRTHDAY);
        }

        if (hasLoginPopup) {
            triggers.push(POPUP_DISPLAY_OPTIONS.AFTER_LOGIN);
        }

        if (hasRegistrationPopup) {
            triggers.push(POPUP_DISPLAY_OPTIONS.AFTER_REGISTRATION);
        }

        return triggers;
    }

    function isPopupEligible(popup, triggers, currentUrl) {
        if (!popup) {
            return false;
        }

        if (!isPopupActive(popup)) {
            return false;
        }

        if (!matchesLanguage(popup) || !matchesCurrency(popup)) {
            return false;
        }

        if (triggers.indexOf(popup.DisplayOptions) < 0) {
            return false;
        }

        if (
            popup.DisplayOptions === POPUP_DISPLAY_OPTIONS.VISIT_PAGE &&
            !matchesUrl(popup, currentUrl)
        ) {
            return false;
        }

        if (isPopupDismissedEffective(popup.Id)) {
            return false;
        }

        if (!canShowPopupByFrequency(popup)) {
            return false;
        }

        return true;
    }

    function buildQueue(popups, triggers) {
        if (!Array.isArray(popups) || !Array.isArray(triggers) || !triggers.length) {
            return [];
        }

        var currentUrl = getCurrentPath();

        return popups.filter(function (popup) {
            return isPopupEligible(popup, triggers, currentUrl);
        });
    }

    function ensurePopupContainer() {
        var container = document.getElementById('js_popup-container');

        if (!container) {
            container = document.createElement('div');
            container.id = 'js_popup-container';
            document.body.appendChild(container);
        }

        return container;
    }

    function clearRenderedPopup() {
        const container =
            document.getElementById('js_popup-container') ||
            document.getElementById('canvas-popup');

        if (!container) {
            return;
        }

        container.remove();
    }

    // function clearRenderedPopup() {
    //     var container = document.getElementById('js_popup-container');

    //     if (!container) {
    //         container = document.getElementById('canvas-popup');
    //         if (!container) {
    //             return;
    //         } else {
    //             container.remove();
    //         }
    //     }

    //     container.innerHTML = '';
    // }

    function consumePopupTriggerIfNeeded(popup) {
        if (!popup) {
            return;
        }

        if (popup.DisplayOptions === POPUP_DISPLAY_OPTIONS.AFTER_LOGIN) {
            consumeLoginTrigger(getCurrentPlayerId());
        }

        if (popup.DisplayOptions === POPUP_DISPLAY_OPTIONS.AFTER_REGISTRATION) {
            consumeRegistrationTrigger(getCurrentPlayerId());
        }
    }

    function renderPopup(html, popup) {
        var container = ensurePopupContainer();

        container.innerHTML = html;
        container.style.display = '';
        delete container.dataset.pausedByBlockingUi;

        state.activePopup = popup;

        consumePopupTriggerIfNeeded(popup);
        bindPopupEvents(container, popup);
    }

    function bindPopupEvents(container, popup) {
        var closeButton = container.querySelector('.popup-close-btn');
        var dismissCheckbox = container.querySelector('.popup-dismiss-checkbox');

        if (!closeButton) {
            return;
        }

        closeButton.addEventListener('click', async function () {
            var isDismissChecked = dismissCheckbox ? dismissCheckbox.checked : false;
            await handlePopupClose(popup, isDismissChecked);
        });
    }

    function isBlockingUiOpen() {
        var href = window.location.href.toLowerCase();

        var hasBlockingUrl =
            href.indexOf('profile') >= 0 ||
            href.indexOf('register') >= 0 ||
            href.indexOf('logdialog') >= 0 ||
            href.indexOf('/play/fun') >= 0 ||
            href.indexOf('/play/real') >= 0;

        return document.body.classList.contains('ofh') || hasBlockingUrl;
    }

    function pauseActivePopupForBlockingUi() {
        var container = document.getElementById('popup-container');

        if (!container || !state.activePopup) {
            return;
        }

        container.dataset.pausedByBlockingUi = '1';
        container.style.display = 'none';
    }

    function scheduleNextPopup(delay) {
        if (state.timerId) {
            clearTimeout(state.timerId);
            state.timerId = null;
        }

        state.timerId = setTimeout(function () {
            state.timerId = null;
            showNextPopupFromQueue();
        }, delay);
    }

    async function showNextPopupFromQueue() {
        if (isBlockingUiOpen()) {
            pauseActivePopupForBlockingUi();
            return;
        }

        while (state.queue.length) {
            var popup = state.queue.shift();

            if (!popup) {
                continue;
            }

            if (!isPopupActive(popup)) {
                removePopupFromStorage(popup.Id);
                continue;
            }

            if (isPopupDismissedEffective(popup.Id)) {
                continue;
            }

            if (!canShowPopupByFrequency(popup)) {
                continue;
            }

            if (popup.PopupType === 2) { //Canvas
                continue;

                //TODO - 
                // var data = await fetchCanvasPopupContent(popup.Id);
                // if (!data) {
                //     continue;
                // }

                // renderCanvasPopup(data, popup);
                // return;
            } else { //HTML
                var content = await fetchPopupContent(popup.Id);
                if (!content) {
                    continue;
                }

                renderPopup(content, popup);
                return;
            }
        }
    }

    async function handlePopupClose(popup, isDismissChecked) {
        if (isLoggedInPopupViewer()) {
            upsertPlayerPopupViewCookie(popup.Id, isDismissChecked);

            try {
                await savePopupSeenStatus(popup.Id, isDismissChecked);
            } catch (e) {
            }
        } else {
            markPopupShownLocal(popup.Id);

            if (isDismissChecked) {
                markPopupDismissedLocal(popup.Id);
            }
        }

        clearRenderedPopup();
        state.activePopup = null;

        scheduleNextPopup(POPUP_STORAGE_TTL.AFTER_CLOSE_DELAY_MS);
    }

    function bindGlobalUiEvents() {
        if (state.eventsBound) {
            return;
        }

        state.eventsBound = true;

        $(document).on('dialogclose', function () {
            setTimeout(async function () {
                if (isBlockingUiOpen()) {
                    return;
                }

                var container = document.getElementById('popup-container');

                if (
                    state.activePopup &&
                    container &&
                    container.dataset.pausedByBlockingUi === '1'
                ) {
                    container.style.display = '';
                    delete container.dataset.pausedByBlockingUi;
                    return;
                }

                if (!state.activePopup && Array.isArray(state.queue) && state.queue.length) {
                    await showNextPopupFromQueue();
                    return;
                }

                await run();
            }, 200);
        });
    }

    async function run() {
        try {
            var thisCallId = ++currentRunCallId;
            consumePopupConfigReset();

            if (!state.areAnnouncementsInitialized && !state.isAnnouncementsInitializing) {
                state.isAnnouncementsInitializing = true;

                try {
                    var plId = getCurrentPlayerId();
                    var changeLoginState = false;
                    var oldState = sessionStorage.getItem('loggedIn') === 'true';
                    if ((plId > 0 && !oldState) || (plId == 0 && oldState)) changeLoginState = true;
                    sessionStorage.setItem('loggedIn', plId > 0);
                    var announcements = await loadAnnouncements(changeLoginState);

                    if (thisCallId !== currentRunCallId) {
                        return;
                    }

                    state.announcementsQueue = buildQueue(announcements, getInitialTriggers(announcements));

                    if (state.announcementsQueue && state.announcementsQueue.length > 0) {
                        var areaSettings = await loadAreaSettings();

                        if (thisCallId !== currentRunCallId) {
                            return;
                        }

                        if (areaSettings) {
                            state.areaSettings = areaSettings;
                        }

                        await initAnnouncements(null, thisCallId);

                        if (thisCallId !== currentRunCallId) {
                            return;
                        }
                    }

                    state.areAnnouncementsInitialized = true;
                } finally {
                    state.isAnnouncementsInitializing = false;
                }
            }

            var popups = await loadPopupConfig();

            if (thisCallId !== currentRunCallId) {
                return;
            }

            if (isLoggedInPopupViewer()) {
                loadPlayerPopupViewsFromCookie(getCurrentPlayerId());
            } else {
                state.playerPopupViews = [];
            }

            state.queue = buildQueue(popups, getInitialTriggers(popups));

            bindGlobalUiEvents();

            if (!state.queue.length) {
                return;
            }

            scheduleNextPopup(POPUP_STORAGE_TTL.INITIAL_DELAY_MS);
        } catch (e) {
            console.error('Popup run error:', e);
        }
    }

    async function initAnnouncements(id = null, runCallId = null) {
        var sliderContainer = $('#announcement_slider');
        var hideUntil = localStorage.getItem(POPUP_STORAGE_KEYS.ANNOUNCEMENTS_HIDDEN_UNTIL);
        if (hideUntil && Date.now() < parseInt(hideUntil, 10) && id === null) {
            sliderContainer.remove();
            return;
        }
        if (state.timerId) clearInterval(state.timerId);
        if (state.rafId) cancelAnimationFrame(state.rafId);
        var $wrapper = $('#js_announcements_container');
        $wrapper.empty();
        var announcementIds = [];
        if (id !== null && id > 0) {
            announcementIds = [id];
        } else if (state.announcementsQueue != null) {
            announcementIds = state.announcementsQueue.map(elem => elem.Id);
        }
        try {
            const filteredIds = filterAnnouncements(announcementIds);
            if (filteredIds.length === 0) {
                return;
            }
            const announcements = await loadAnnouncementContents(filteredIds);
            if (announcements === null || announcements.length === 0) {
                return;
            }
            state.announcementValidIds = announcementIds;
            var validSlides = announcements.map(elem => elem.Body).filter(slide => slide !== null && slide !== undefined);
            state.validSlidesCount = validSlides.length ?? 0;
            var isHorizontal = state.areaSettings.SliderAnimationType === SLIDER_ANIMATION_TYPE.HORIZONTAL;
            var isFaded = state.areaSettings.SliderAnimationType === SLIDER_ANIMATION_TYPE.FADED;

            if (
                isHorizontal &&
                !state.areaSettings.IsAutoplayOn
            ) {
                sliderContainer.removeClass('is-autoplay-mode');
            } else {
                sliderContainer.addClass('is-autoplay-mode');
            }
            var speedKeys = { 1: 'Slow', 2: 'Normal', 3: 'Fast' };
            var speedLevel = speedKeys[state.areaSettings.AnimationSpeed] || 'Normal';
            var trackHtml = isHorizontal ? '<div class="slides-track"></div>' : '';
            var $track = isHorizontal ? $(trackHtml) : $wrapper;
            var isRtl = document.documentElement.classList.contains('cw-rtl-global');
            var slidesToRender = isHorizontal && isRtl
                ? validSlides.slice().reverse()
                : validSlides;
            slidesToRender.forEach(slideHtml => {
                var $slide = $(`
                <div class="slide-item">
                    <div class="notification_slide">
                        <div class="js-announcement-text">${slideHtml}</div>
                    </div>
                </div>`);
                $track.append($slide);
            });
            if (isHorizontal && state.validSlidesCount > 0) {
                var $originalSequence = $track.find('.slide-item').clone();
                for (var cloneSetIndex = 0; cloneSetIndex < 1; cloneSetIndex++) {
                    $originalSequence.each(function () {
                        var $clone = $(this)
                            .clone()
                            .attr('aria-hidden', 'true');
                        $track.append($clone);
                    });
                }
            }
            if (isHorizontal) {
                var $scrollerWrapper = $('<div class="ticker-scroller-wrapper"></div>')
                    .css({
                        animation: 'none',
                        visibility: 'hidden',
                        transform: 'none'
                    })
                    .append($track);
                $wrapper.append($scrollerWrapper);
                sliderContainer.removeClass('is-faded-mode').addClass('is-horizontal-mode');
            } else {
                sliderContainer.removeClass('is-horizontal-mode').addClass('is-faded-mode');
            }
            if (state.areaSettings.IsBlockIconOn && state.areaSettings.BlockIcon) {
                var imageContent = `<img src="${state.context.baseUrl}/${state.areaSettings.BlockIcon}" alt="icon">`;
                $('#notification_icon_div').html(imageContent);
            } else {
                $('#notification_icon_div').empty();
            }
        } catch (e) {
            sliderContainer.remove();
            return;
        }
        if (state.areaSettings.BackgroundColor) {
            sliderContainer.find('.notification_content').attr('style', function (i, s) { return (s || '') + `background-color: ${state.areaSettings.BackgroundColor} !important;`; });
            $(".faded_hidden_content").attr('style', function (i, s) { return (s || '') + `background-color: ${state.areaSettings.BackgroundColor} !important;`; });
        }
        if (state.areaSettings.TextColor) {
            sliderContainer.attr('style', function (i, s) { return (s || '') + `color: ${state.areaSettings.TextColor} !important;`; });
            $('#announcement_slider_prev, #announcement_slider_next').attr('style', function (i, s) { return (s || '') + `color: ${state.areaSettings.TextColor} !important;`; });
            $('#notification_close_btn_block').attr('style', function (i, s) { return (s || '') + `color: ${state.areaSettings.TextColor} !important;`; });
            sliderContainer.find('.js-announcement-text').each(function () {
                $(this).attr('style', function (i, s) { return (s || '') + `color: ${state.areaSettings.TextColor} !important;`; });
            });
            $(".faded_hidden_content").attr('style', function (i, s) { return (s || '') + `color: ${state.areaSettings.TextColor} !important;`; });
        }
        sliderContainer.removeClass("d-none");
        if (isHorizontal) {
            $('#announcement_slider_prev, #announcement_slider_next').hide();
            sliderContainer.toggleClass("is-single", state.validSlidesCount <= 1);
        } else if (state.validSlidesCount > 1) {
            $('#announcement_slider_prev, #announcement_slider_next').show();
            sliderContainer.removeClass("is-single");
        } else {
            $('#announcement_slider_prev, #announcement_slider_next').hide();
            sliderContainer.addClass("is-single");
        }
        showHiddenContent(isFaded || isHorizontal);
        if (isHorizontal) {
            var $slides = $track.find('.slide-item');
            var totalOriginalSlides = state.validSlidesCount;
            if ($slides.length === 0 || totalOriginalSlides === 0) {
                bindAnnouncements();
                return;
            }
            var $originalSlides = $slides.slice(0, totalOriginalSlides);
            var $hiddenContent = $('.faded_hidden_content');
            var resizeTimer = null;
            var fallbackSpeeds = {
                Slow: 40,
                Normal: 70,
                Fast: 120
            };
            var pixelsPerSecond = fallbackSpeeds[speedLevel] || 70;
            if (
                typeof HORIZONTAL_ANIMATION_OPTIONS !== 'undefined' &&
                HORIZONTAL_ANIMATION_OPTIONS[speedLevel]
            ) {
                pixelsPerSecond =
                    HORIZONTAL_ANIMATION_OPTIONS[speedLevel].PixelsPerSecond ||
                    pixelsPerSecond;
            }
            if (!document.getElementById('announcement-horizontal-styles')) {
                $('<style>', {
                    id: 'announcement-horizontal-styles',
                    text: `
                @keyframes announcement-marquee-ltr {
                    from {
                        transform: translate3d(
                            var(--announcement-animation-start-x),
                            0,
                            0
                        );
                    }
                    to {
                        transform: translate3d(
                            var(--announcement-animation-end-x),
                            0,
                            0
                        );
                    }
                }
                @keyframes announcement-marquee-rtl {
                    from {
                        transform: translate3d(
                            var(--announcement-animation-start-x),
                            0,
                            0
                        );
                    }
                    to {
                        transform: translate3d(
                            var(--announcement-animation-end-x),
                            0,
                            0
                        );
                    }
                }
                #announcement_slider.is-horizontal-mode #js_announcements_container {
                    display: block;
                    position: relative;
                    overflow: hidden;
                    direction: ltr;
                }
                #announcement_slider.is-horizontal-mode .ticker-scroller-wrapper {
                    display: flex;
                    width: max-content;
                    min-width: max-content;
                    will-change: transform;
                    animation-name: var(--announcement-animation-name);
                    animation-duration: var(--announcement-animation-duration);
                    animation-timing-function: linear;
                    animation-iteration-count: infinite;
                    animation-play-state: running;
                }
                #announcement_slider.is-horizontal-mode .ticker-scroller-wrapper.is-paused {
                    animation-play-state: paused;
                }
                #announcement_slider.is-horizontal-mode .slides-track {
                    display: flex;
                    flex-wrap: nowrap;
                    width: max-content;
                    min-width: max-content;
                    box-sizing: content-box;
                    padding-left: 0;
                    padding-right: 0;
                }
                #announcement_slider.is-horizontal-mode .slide-item {
                    display: flex;
                    flex: 0 0 auto;
                    width: max-content;
                    min-width: max-content;
                    padding-inline-end: var(--announcement-slide-gap);
                    box-sizing: content-box;
                }
                #announcement_slider.is-horizontal-mode .notification_slide,
                #announcement_slider.is-horizontal-mode .js-announcement-text {
                    width: max-content;
                    min-width: max-content;
                    max-width: none;
                    white-space: nowrap;
                }
                #announcement_slider.is-horizontal-mode .js-announcement-text > * {
                    display: inline;
                    margin-block: 0;
                }
            `
                }).appendTo(document.head);
            }
            $wrapper.css({
                direction: 'ltr',
                display: 'block',
                overflow: 'hidden',
                position: 'relative'
            });
            $track.find('.notification_slide, .js-announcement-text').css(
                'direction',
                isRtl ? 'rtl' : 'ltr'
            );
            var setPaused = function (paused) {
                state.isContentHovered = paused;
                $scrollerWrapper.toggleClass('is-paused', paused);
                $scrollerWrapper[0].style.setProperty(
                    'animation-play-state',
                    paused ? 'paused' : 'running',
                    'important'
                );
            };
            var closeHiddenContent = function () {
                clearTimeout(hoverResumeTimer);
                $hiddenContent
                    .stop(true, true)
                    .fadeOut(150, function () {
                        $(this)
                            .removeClass('d-block')
                            .addClass('d-none')
                            .empty();
                    });
            };
            var openHiddenContent = function ($slide) {
                var $announcementText = $slide
                    .find('.js-announcement-text')
                    .first();
                if (!$announcementText.length || !$wrapper[0]) {
                    return;
                }
                var html = $announcementText.html();
                if (!html || !html.trim()) {
                    return;
                }
                var textWidth = Math.ceil(
                    $announcementText[0].getBoundingClientRect().width
                );
                var viewportWidth = Math.ceil(
                    $wrapper[0].getBoundingClientRect().width
                );
                if (textWidth <= viewportWidth) {
                    closeHiddenContent();
                    return;
                }
                if (state.context.isMobile) {
                    html += `
                <span id="faded_hidden_notification_close_btn_block"
                      class="faded_hidden_notification_close_btn">
                    <i class="cw_icon_close_v4 ico_size-xs"></i>
                </span>`;
                }
                $hiddenContent
                    .html(html)
                    .removeClass('d-none')
                    .addClass('d-block')
                    .stop(true, true)
                    .fadeIn(150);
                if (state.areaSettings.TextColor) {
                    $hiddenContent.css(
                        'color',
                        state.areaSettings.TextColor
                    );
                    $('#faded_hidden_notification_close_btn_block').css(
                        'color',
                        state.areaSettings.TextColor
                    );
                }
            };
            var animationRunId = 0;
            var mobileAnimationStartTimer = null;
            var lastCalculatedViewportWidth = 0;
            var stopPendingHorizontalAnimationStart = function () {
                if (mobileAnimationStartTimer) {
                    clearTimeout(mobileAnimationStartTimer);
                    mobileAnimationStartTimer = null;
                }
                if (state.rafId) {
                    cancelAnimationFrame(state.rafId);
                    state.rafId = null;
                }
            };
            var calculateAnimation = function () {
                if (
                    !$wrapper[0] ||
                    !$scrollerWrapper[0] ||
                    !$track[0] ||
                    !$originalSlides.length
                ) {
                    return;
                }
                var currentAnimationRunId = ++animationRunId;
                var scrollerElement = $scrollerWrapper[0];
                var trackElement = $track[0];
                stopPendingHorizontalAnimationStart();
                scrollerElement.style.setProperty('animation', 'none', 'important');
                scrollerElement.style.setProperty(
                    'animation-play-state',
                    'paused',
                    'important'
                );
                scrollerElement.style.setProperty(
                    'transform',
                    'translate3d(0, 0, 0)',
                    'important'
                );
                $scrollerWrapper.css('visibility', 'hidden');
                var viewportWidth = Math.ceil(
                    $wrapper[0].getBoundingClientRect().width
                );
                if (viewportWidth <= 0) {
                    return;
                }
                lastCalculatedViewportWidth = viewportWidth;
                trackElement.style.setProperty(
                    '--announcement-slide-gap',
                    viewportWidth + 'px'
                );
                if (state.context.isMobile && !isRtl) {
                    trackElement.style.setProperty(
                        'padding-left',
                        viewportWidth + 'px'
                    );
                    trackElement.style.setProperty('padding-right', '0px');
                } else {
                    trackElement.style.setProperty('padding-left', '0px');
                    trackElement.style.setProperty('padding-right', '0px');
                }
                var $allSlides = $track.find('.slide-item');
                var firstOriginalElement = $allSlides.get(0);
                var firstCloneElement = $allSlides.get(totalOriginalSlides);
                if (!firstOriginalElement || !firstCloneElement) {
                    return;
                }
                var trackRect = trackElement.getBoundingClientRect();
                var firstOriginalRect = firstOriginalElement.getBoundingClientRect();
                var firstCloneRect = firstCloneElement.getBoundingClientRect();
                var originalStartLeft = firstOriginalRect.left - trackRect.left;
                var cloneStartLeft = firstCloneRect.left - trackRect.left;
                var loopWidth = cloneStartLeft - originalStartLeft;
                if (loopWidth <= 0 || pixelsPerSecond <= 0) {
                    return;
                }
                var startX;
                var endX;
                if (isRtl) {
                    var rtlBoundaryOffset = 1;
                    if (!state.context.isMobile) {
                        var logicalFirstElement = $originalSlides.get(totalOriginalSlides - 1);
                        var logicalFirstRect = logicalFirstElement.getBoundingClientRect();
                        var logicalFirstStartLeft = logicalFirstRect.left - trackRect.left;
                        startX = -logicalFirstStartLeft + rtlBoundaryOffset;
                        endX = startX + loopWidth;
                    } else {
                        startX = -loopWidth + rtlBoundaryOffset;
                        endX = rtlBoundaryOffset;
                    }
                } else if (state.context.isMobile) {
                    startX = 0;
                    endX = -loopWidth;
                } else {
                    startX = viewportWidth - originalStartLeft;
                    endX = startX - loopWidth;
                }
                var animationDistance = Math.abs(endX - startX);
                if (animationDistance <= 0 || pixelsPerSecond <= 0) {
                    return;
                }
                var duration = animationDistance / pixelsPerSecond;
                var animationName =
                    'announcement-marquee-run-' +
                    Date.now() +
                    '-' +
                    animationRunId;
                var styleSheet = document.getElementById(
                    'announcement-horizontal-runtime-styles'
                );
                if (!styleSheet) {
                    styleSheet = document.createElement('style');
                    styleSheet.id = 'announcement-horizontal-runtime-styles';
                    document.head.appendChild(styleSheet);
                }
                styleSheet.textContent =
                    '@keyframes ' + animationName + ' {' +
                    '0% { transform: translate3d(' + startX + 'px, 0, 0); }' +
                    '100% { transform: translate3d(' + endX + 'px, 0, 0); }' +
                    '}';
                if (currentAnimationRunId !== animationRunId) {
                    return;
                }
                scrollerElement.style.setProperty(
                    'transform',
                    'translate3d(' + startX + 'px, 0, 0)',
                    'important'
                );
                scrollerElement.style.setProperty('animation', 'none', 'important');
                scrollerElement.style.setProperty(
                    'animation-play-state',
                    'paused',
                    'important'
                );
                $scrollerWrapper.css('visibility', 'visible');
                var beginAnimation = function () {
                    if (currentAnimationRunId !== animationRunId) {
                        return;
                    }
                    if (
                        !$scrollerWrapper[0] ||
                        !document.documentElement.contains($scrollerWrapper[0])
                    ) {
                        return;
                    }
                    state.rafId = requestAnimationFrame(function () {
                        state.rafId = null;
                        if (currentAnimationRunId !== animationRunId) {
                            return;
                        }
                        var element = $scrollerWrapper[0];
                        element.style.removeProperty('transform');
                        element.style.setProperty(
                            'animation',
                            animationName + ' ' + duration + 's linear infinite',
                            'important'
                        );
                        element.style.setProperty(
                            'animation-play-state',
                            state.isContentHovered ? 'paused' : 'running',
                            'important'
                        );
                    });
                };
                if (state.context.isMobile) {
                    mobileAnimationStartTimer = setTimeout(function () {
                        mobileAnimationStartTimer = null;
                        beginAnimation();
                    }, 80);
                } else {
                    beginAnimation();
                }
            };
            var hoverResumeTimer = null;
            var isDesktopAnnouncementHovered = function () {
                return (
                    $('#js_announcements_container:hover').length > 0 ||
                    $('.faded_hidden_content:hover').length > 0
                );
            };
            var scheduleHoverResume = function () {
                clearTimeout(hoverResumeTimer);
                hoverResumeTimer = setTimeout(function () {
                    if (state.context.isMobile) {
                        return;
                    }
                    if (isDesktopAnnouncementHovered()) {
                        setPaused(true);
                        return;
                    }
                    setPaused(false);
                    closeHiddenContent();
                }, 80);
            };
            $(document).off('.horizontalAnnouncements');
            $wrapper.off('.horizontalAnnouncements');
            $hiddenContent.off('.horizontalAnnouncements');
            $slides.off('.horizontalAnnouncements');
            $wrapper
                .on('mouseenter.horizontalAnnouncements pointerenter.horizontalAnnouncements', function () {
                    if (state.context.isMobile) {
                        return;
                    }
                    clearTimeout(hoverResumeTimer);
                    setPaused(true);
                })
                .on('mouseleave.horizontalAnnouncements pointerleave.horizontalAnnouncements', function () {
                    if (state.context.isMobile) {
                        return;
                    }
                    scheduleHoverResume();
                });
            $slides.on('mouseenter.horizontalAnnouncements pointerenter.horizontalAnnouncements', function () {
                if (state.context.isMobile) {
                    return;
                }
                clearTimeout(hoverResumeTimer);
                setPaused(true);
                openHiddenContent($(this));
            });
            $hiddenContent
                .on('mouseenter.horizontalAnnouncements pointerenter.horizontalAnnouncements', function () {
                    if (state.context.isMobile) {
                        return;
                    }
                    clearTimeout(hoverResumeTimer);
                    setPaused(true);
                })
                .on('mouseleave.horizontalAnnouncements pointerleave.horizontalAnnouncements', function () {
                    if (state.context.isMobile) {
                        return;
                    }
                    scheduleHoverResume();
                });
            $(document)
                .on(
                    'click.horizontalAnnouncements',
                    '#js_announcements_container .slide-item',
                    function (e) {
                        if (!state.context.isMobile) return;
                        if ($(e.target).closest('a, button').length) return;
                        var shouldPause = !state.isContentHovered;
                        setPaused(shouldPause);
                        if (shouldPause) {
                            openHiddenContent($(this));
                        } else {
                            closeHiddenContent();
                        }
                    }
                )
                .on(
                    'click.horizontalAnnouncements',
                    '.faded_hidden_notification_close_btn',
                    function (e) {
                        e.preventDefault();
                        e.stopPropagation();
                        setPaused(false);
                        closeHiddenContent();
                    }
                );
            $(window)
                .off('resize.horizontalAnnouncements')
                .on('resize.horizontalAnnouncements', function () {
                    clearTimeout(resizeTimer);
                    var nextViewportWidth = $wrapper[0]
                        ? Math.ceil($wrapper[0].getBoundingClientRect().width)
                        : 0;
                    if (
                        state.context.isMobile &&
                        nextViewportWidth > 0 &&
                        Math.abs(nextViewportWidth - lastCalculatedViewportWidth) < 2
                    ) {
                        return;
                    }
                    animationRunId++;
                    stopPendingHorizontalAnimationStart();
                    resizeTimer = setTimeout(function () {
                        calculateAnimation();
                    }, state.context.isMobile ? 250 : 150);
                });
            var $images = $track.find('img');
            var startAnimation = function () {
                var runCalculation = function () {
                    setTimeout(calculateAnimation, 0);
                };
                if (document.fonts && document.fonts.ready) {
                    document.fonts.ready.then(runCalculation, runCalculation);
                } else {
                    runCalculation();
                }
            };
            if ($images.length) {
                var pendingImages = $images.length;
                var imageReady = function () {
                    pendingImages--;
                    if (pendingImages <= 0) startAnimation();
                };
                $images.each(function () {
                    if (this.complete) {
                        imageReady();
                    } else {
                        $(this).one('load error', imageReady);
                    }
                });
            } else {
                startAnimation();
            }
        }
        if (isFaded) {
            var $slides = $wrapper.find('.slide-item');
            var fadeParams = FADED_ANIMATION_OPTIONS[speedLevel] || FADED_ANIMATION_OPTIONS.Normal;
            sliderContainer.css('--fade-duration', `${fadeParams.FadeDuration}ms`);
            $slides.removeClass('active');
            state.currentFadedIndex = 0;
            $slides.eq(0).addClass('active');
            var changeFadedSlide = function (direction) {
                var $currentSlide = $slides.eq(state.currentFadedIndex);
                $currentSlide.removeClass('active');
                if (direction === 'next') {
                    state.currentFadedIndex = (state.currentFadedIndex + 1) % $slides.length;
                } else {
                    state.currentFadedIndex = (state.currentFadedIndex - 1 + $slides.length) % $slides.length;
                }
                var $nextSlide = $slides.eq(state.currentFadedIndex);
                $nextSlide.addClass('active');
                var $hiddenContent = $('.faded_hidden_content');
                if (state.context.isMobile && !$hiddenContent.hasClass('d-none')) {
                    var fullHtml = $nextSlide.find('.js-announcement-text').html();
                    fullHtml = fullHtml +
                        `
<span id="faded_hidden_notification_close_btn_block" class="faded_hidden_notification_close_btn">
    <i class="cw_icon_close_v4 ico_size-xs"></i>
</span>
`;
                    if (fullHtml && fullHtml.trim() !== "") {
                        $hiddenContent.html(fullHtml).removeClass('d-none').addClass('d-block').stop().fadeIn(200);
                    }
                    if (state.areaSettings.TextColor) {
                        $('#faded_hidden_notification_close_btn_block').attr('style', function (i, s) { return (s || '') + `color: ${state.areaSettings.TextColor} !important;`; });
                    }
                }
                else if (!state.context.isMobile && !$hiddenContent.hasClass('d-none')) {
                    if (state.isContentHovered) {
                        return;
                    }
                    var fullHtml = $nextSlide.find('.js-announcement-text').html();
                    if (fullHtml && fullHtml.trim() !== "") {
                        $hiddenContent.html(fullHtml);
                    }
                }
            };
            var startFadedTimer = function () {
                clearInterval(state.timerId);
                state.timerId = setInterval(function () {
                    if (state.areaSettings.IsAutoplayOn && $slides.length > 1) {
                        changeFadedSlide('next');
                    } else {
                        var currentIndex = state.currentFadedIndex;
                        $slides.eq(currentIndex).removeClass('active');
                        setTimeout(function () {
                            $slides.eq(currentIndex).addClass('active');
                        }, fadeParams.FadeDuration);
                    }
                }, fadeParams.VisibleTime * 1000);
            };
            $('#announcement_slider_next')
                .off('click.faded')
                .on('click.faded', function () {
                    changeFadedSlide('next');
                    startFadedTimer();
                });
            $('#announcement_slider_prev')
                .off('click.faded')
                .on('click.faded', function () {
                    changeFadedSlide('prev');
                    startFadedTimer();
                });
            setTimeout(startFadedTimer, 100);
        }
        bindAnnouncements();
    }

    function showHiddenContent(isFaded) {
        var $hiddenContent = $('#announcement_slider').next('.faded_hidden_content');
        if ($hiddenContent.length === 0) {
            $hiddenContent = $('.faded_hidden_content');
        }

        if (typeof state.isContentHovered === 'undefined') {
            state.isContentHovered = false;
        }

        $(document).off('mouseenter mouseleave', '#announcement_slider .slide-item');
        $(document).off('click', '#faded_hidden_notification_close_btn_block');
        $('#announcement_slider').off('mouseenter mouseleave');
        $hiddenContent.off('mouseenter mouseleave');

        if (isFaded) {
            if (state.context.isMobile) {
                $(document).on('mouseenter', '#announcement_slider .slide-item', function () {
                    if ($('#announcement_slider').hasClass('is-faded-mode')) {
                        var fullHtml = $(this).find('.js-announcement-text').html();
                        fullHtml = fullHtml +
                            `
                            <span id="faded_hidden_notification_close_btn_block" class="faded_hidden_notification_close_btn">
                                <i class="cw_icon_close_v4 ico_size-xs"></i>
                            </span>
                            `;
                        if (fullHtml && fullHtml.trim() !== "") {
                            $hiddenContent.html(fullHtml).removeClass('d-none').addClass('d-block').stop().fadeIn(200);
                        }

                        if (state.areaSettings.TextColor) {
                            $('#faded_hidden_notification_close_btn_block').attr('style', function (i, s) { return (s || '') + `color: ${state.areaSettings.TextColor} !important;`; });
                        }
                    }
                });

                $(document).on('click', '#faded_hidden_notification_close_btn_block', function (e) {
                    $hiddenContent.stop().fadeOut(200, function () {
                        $(this).removeClass('d-block').addClass('d-none').empty();
                    });
                });
            } else {
                var handleMouseEnter = function () {
                    state.isContentHovered = true;
                };

                $('#announcement_slider').on('mouseenter', handleMouseEnter);
                $hiddenContent.on('mouseenter', handleMouseEnter);

                $(document).on('mouseenter', '#announcement_slider .slide-item', function () {
                    if ($('#announcement_slider').hasClass('is-faded-mode')) {
                        if ($hiddenContent.hasClass('d-none') || $hiddenContent.is(':hidden')) {
                            var fullHtml = $(this).find('.js-announcement-text').html();
                            if (fullHtml && fullHtml.trim() !== "") {
                                $hiddenContent.html(fullHtml).removeClass('d-none').stop().fadeIn(200);
                            }
                        }
                    }
                });

                var handleMouseLeave = function () {
                    setTimeout(function () {
                        var completelyOut = !$('#announcement_slider').is(':hover') && !$hiddenContent.is(':hover');

                        if (completelyOut) {
                            state.isContentHovered = false;
                            $hiddenContent.stop().fadeOut(200, function () {
                                $(this).addClass('d-none').empty();
                            });
                        }
                    }, 50);
                };

                $('#announcement_slider').on('mouseleave', handleMouseLeave);
                $hiddenContent.on('mouseleave', handleMouseLeave);
            }

        } else {
            state.isContentHovered = false;
            $hiddenContent.addClass('d-none').hide().empty();
        }
    }

    function bindAnnouncements() {
        var $slider = $('#announcement_slider');

        $(document).off('click', '#notification_close_btn_block');

        if (!state.areaSettings.IsMakeAnnouncementPermanentOn) {
            $("#notification_close_btn_block").show();

            $(document).on('click', '#notification_close_btn_block', function (e) {
                e.preventDefault();
                e.stopPropagation();

                hideAnnouncements(state.announcementValidIds);

                if (state.timerId) {
                    clearInterval(state.timerId);
                    state.timerId = null;
                }
                if (state.rafId) {
                    cancelAnimationFrame(state.rafId);
                    state.rafId = null;
                }

                $('#announcement_slider').remove();
            });
        } else {
            $("#notification_close_btn_block").hide();
        }

        var $hiddenContent = $slider.find(
            '.faded_hidden_content'
        );

        var canHover = window.matchMedia(
            '(hover: hover) and (pointer: fine)'
        ).matches;

        $slider.off('.announcements');

        if (canHover) {
            $slider.on(
                'mouseenter.announcements',
                '.slide-item .notification_slide',
                function () {
                    var $announcementText = $(this)
                        .find('.js-announcement-text')
                        .first();

                    if (!$announcementText.length) {
                        return;
                    }

                    var contentHtml = $announcementText.html();

                    if (!contentHtml || !contentHtml.trim()) {
                        return;
                    }

                    var $visibleContainer = $slider.find(
                        '#js_announcements_container'
                    );

                    var textWidth = Math.ceil(
                        $announcementText[0].getBoundingClientRect().width
                    );

                    var visibleWidth = Math.ceil(
                        $visibleContainer[0].getBoundingClientRect().width
                    );

                    if (textWidth <= visibleWidth) {
                        return;
                    }

                    state.isContentHovered = true;

                    $hiddenContent
                        .html(contentHtml)
                        .removeClass('d-none')
                        .addClass('d-block');

                    $slider
                        .find('.ticker-scroller-wrapper')
                        .addClass('is-paused');
                }
            );

            $slider.on(
                'mouseleave.announcements',
                '.slide-item .notification_slide',
                function (event) {
                    var relatedTarget = event.relatedTarget;

                    if (
                        relatedTarget &&
                        $(relatedTarget)
                            .closest('.faded_hidden_content')
                            .length
                    ) {
                        return;
                    }

                    hideAnnouncementHiddenContent(
                        $slider,
                        $hiddenContent
                    );
                }
            );

            $slider.on(
                'mouseenter.announcements',
                '.faded_hidden_content',
                function () {
                    state.isContentHovered = true;

                    $slider
                        .find('.ticker-scroller-wrapper')
                        .addClass('is-paused');
                }
            );

            $slider.on(
                'mouseleave.announcements',
                '.faded_hidden_content',
                function () {
                    hideAnnouncementHiddenContent(
                        $slider,
                        $hiddenContent
                    );
                }
            );
        } else {

            state.isContentHovered = false;

            $hiddenContent
                .empty()
                .removeClass('d-block')
                .addClass('d-none');

            $slider
                .find('.ticker-scroller-wrapper')
                .removeClass('is-paused')
                .css('animation-play-state', 'running');
        }
    }

    function hideAnnouncementHiddenContent(
        $slider,
        $hiddenContent
    ) {
        state.isContentHovered = false;

        $hiddenContent
            .empty()
            .removeClass('d-block')
            .addClass('d-none');

        $slider
            .find('.ticker-scroller-wrapper')
            .removeClass('is-paused')
            .css('animation-play-state', 'running');
    }

    function hideAnnouncements(ids) {
        let hidden = JSON.parse(
            localStorage.getItem(POPUP_STORAGE_KEYS.HIDDEN_ANNOUNCEMENTS) || '{}'
        );

        const expireAt = Date.now() + (24 * 60 * 60 * 1000);

        ids.forEach(id => {
            hidden[id] = expireAt;
        });

        localStorage.setItem(
            POPUP_STORAGE_KEYS.HIDDEN_ANNOUNCEMENTS,
            JSON.stringify(hidden)
        );
    }

    function filterAnnouncements(ids) {
        const hidden = JSON.parse(
            localStorage.getItem(POPUP_STORAGE_KEYS.HIDDEN_ANNOUNCEMENTS) || '{}'
        );

        if (hidden === null || hidden === undefined) {
            return ids
        }

        const now = Date.now();

        return ids.filter(id => {
            return !hidden[id] || hidden[id] < now;
        });
    }

    async function initPreview() {
        try {
            bindGlobalUiEvents();

            var previewPopupId = Number(state.context.previewPopupId) || 0;

            if (previewPopupId <= 0) {
                return;
            }

            var content = await fetchPopupContent(previewPopupId);

            if (!content) {
                return;
            }

            var container = ensurePopupContainer();
            container.innerHTML = content;
            container.style.display = '';
            delete container.dataset.pausedByBlockingUi;

            state.activePopup = null;

            var closeButton = container.querySelector('.popup-close-btn');

            if (closeButton) {
                closeButton.addEventListener('click', function () {
                    clearRenderedPopup();
                    state.activePopup = null;
                });
            }
        } catch (e) {
        }
    }

    function waitForNextAnnouncementFrame() {
        return new Promise(function (resolve) {
            requestAnimationFrame(function () {
                requestAnimationFrame(resolve);
            });
        });
    }

    async function initAnnouncementPreview() {
        try {
            bindGlobalUiEvents();
            var previewAnnouncementId = Number(state.context.previewPopupId) || 0;
            if (previewAnnouncementId <= 0) {
                return;
            }

            var areaSettings = await fetchBrandAreaSettings();
            if (areaSettings) {
                state.areaSettings = areaSettings;
            }

            await initAnnouncements(previewAnnouncementId);
        } catch (e) {
        }
    }

    async function loadAreaSettings() {
        var storedAreaSettings = getStoredAreaSettings();

        if (storedAreaSettings !== null) {
            return storedAreaSettings;
        }

        var areaSettings = await fetchBrandAreaSettings();
        saveAreaSettings(areaSettings);
        return areaSettings;
    }

    async function loadAnnouncements(changeLoginState = false) {
        var storedAnnouncements = getStoredAnnouncements();

        if (storedAnnouncements !== null && !changeLoginState) {
            return storedAnnouncements;
        }

        var announcements = await fetchBrandAnnouncements();
        saveAnnouncements(announcements);

        return normalizeData(announcements);
    }

    async function loadAnnouncementContents(ids) {
        var changedLanguage = isChangedLanguage();
        if (!changedLanguage) {
            var storedAnnouncementContents = getStoredAnnouncementContents(ids);

            if (storedAnnouncementContents !== null && storedAnnouncementContents.length > 0) {
                return storedAnnouncementContents;
            }
        }

        var announcementContents = await fetchAnnouncementContent(ids);
        saveAnnouncementContents(announcementContents, ids);
        return announcementContents;
    }

    function isChangedLanguage() {
        var languageId = getDocumentLanguage();
        var changeLanguageState = false;
        var oldLanguage = sessionStorage.getItem('languageCode');
        if (languageId !== oldLanguage) changeLanguageState = true;
        sessionStorage.setItem('languageCode', languageId);
        return changeLanguageState
    }

    function saveAreaSettings(settings) {
        var payload = {
            data: settings,
            savedAt: Date.now(),
            expiresAt: Date.now() + POPUP_STORAGE_TTL.CONFIG_MS
        };

        localStorage.setItem(POPUP_STORAGE_KEYS.AREA_SETTINGS, JSON.stringify(payload));
    }

    function saveAnnouncements(announcements) {
        var payload = {
            data: normalizeData(announcements),
            savedAt: Date.now(),
            expiresAt: Date.now() + POPUP_STORAGE_TTL.CONFIG_MS
        };

        localStorage.setItem(POPUP_STORAGE_KEYS.ANNOUNCEMENTS, JSON.stringify(payload));
    }


    async function fetchAnnouncementContent(ids) {
        var response = await fetch('/DynamicPopUp/AnnouncementContent', {
            method: 'POST',
            credentials: 'include',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
            },
            body: new URLSearchParams({ idsString: ids.toString() }).toString()
        });

        if (response.ok) {
            return await response.json();
        } else {
            console.error("Error Fetch Announcement Content", response.status);
            return null;
        }
    }

    function getStoredAreaSettings() {
        var raw = localStorage.getItem(POPUP_STORAGE_KEYS.AREA_SETTINGS);

        if (!raw) {
            return null;
        }

        try {
            var payload = JSON.parse(raw);

            if (!payload || !payload.expiresAt || Date.now() > payload.expiresAt || payload.data.length === 0) {
                localStorage.removeItem(POPUP_STORAGE_KEYS.AREA_SETTINGS);
                return null;
            }

            return payload.data;
        } catch (e) {
            localStorage.removeItem(POPUP_STORAGE_KEYS.AREA_SETTINGS);
            return null;
        }
    }

    function getStoredAnnouncementContents(ids) {
        var raw = localStorage.getItem(`${POPUP_STORAGE_KEYS.ANNOUNCEMENT_CONTENTS}_${ids.join('_')}`);

        if (!raw) {
            return [];
        }

        try {
            var payload = JSON.parse(raw);

            if (!payload || !payload.expiresAt || Date.now() > payload.expiresAt) {
                localStorage.removeItem(`${POPUP_STORAGE_KEYS.ANNOUNCEMENT_CONTENTS}_${ids.join('_')}`);
                return [];
            }

            var storedContents = normalizeData(Array.isArray(payload.data) ? payload.data : []);

            if (!Array.isArray(ids) || ids.length === 0) {
                return [];
            }

            var idSet = new Set(
                ids.map(function (id) {
                    return String(id);
                })
            );

            return storedContents.filter(function (announcement) {
                return idSet.has(String(announcement.Id));
            });
        } catch (e) {
            localStorage.removeItem(`${POPUP_STORAGE_KEYS.ANNOUNCEMENT_CONTENTS}_${ids.join('_')}`);
            return [];
        }
    }


    function saveAnnouncementContents(announcementContents, ids = []) {
        var normalizedContents = normalizeData(announcementContents);
        var now = Date.now();

        var payload = {
            data: normalizedContents,
            savedAt: now,
            expiresAt: now + POPUP_STORAGE_TTL.CONFIG_MS
        };

        localStorage.setItem(`${POPUP_STORAGE_KEYS.ANNOUNCEMENT_CONTENTS}_${ids.join('_')}`, JSON.stringify(payload));
    }

    function getStoredAnnouncements(ids) {
        var raw = localStorage.getItem(POPUP_STORAGE_KEYS.ANNOUNCEMENTS);

        if (!raw) {
            return null;
        }

        try {
            var payload = JSON.parse(raw);

            if (!payload || !payload.expiresAt || Date.now() > payload.expiresAt) {
                localStorage.removeItem(POPUP_STORAGE_KEYS.ANNOUNCEMENTS);
                return null;
            }

            return normalizeData(Array.isArray(payload.data) ? payload.data : []);
        } catch (e) {
            localStorage.removeItem(POPUP_STORAGE_KEYS.ANNOUNCEMENTS);
            return null;
        }
    }

    function renderCanvasPopup(data, popup) {
        $("#canvas-popup").removeClass("d-none");

        const $header = $("#popup-header").empty();
        const $body = $("#popup-body").empty();
        const $footer = $("#popup-footer").empty();

        // $header.append(`<i class="cw_icon_close_v4 popup-close-btn"></i>`);
        $header.append(` <span id="announcement_close_btn_block" class="notification_close_btn">
                    <i class="cw_icon_close_v4 popup-close-btn ico_size-xs"></i>
                </span>`);

        var container = document.getElementById('canvas-popup');
        var closeButton = container.querySelector('.popup-close-btn');

        if (data.IsHeaderOn) {
            $("#popup-main-close-button-div").remove();
            renderAbsoluteElements($header, data.Header, state.context.baseUrl);
        } else {
            $("#popup-header-container").remove();
        }

        if (closeButton) {
            bindPopupEvents(container, popup);
        }

        renderAbsoluteElements($body, data.Body, state.context.baseUrl, true);

        if (data.IsFooterOn) {
            renderAbsoluteElements($footer, data.Footer, state.context.baseUrl);
        }

        state.activePopup = popup;
        consumePopupTriggerIfNeeded(popup);
    }

    async function fetchCanvasPopupContent(popupId) {
        var response = await fetch(`/DynamicPopUp/CanvasPopupContent?id=${encodeURIComponent(popupId)}`, {
            method: 'GET',
            credentials: 'include',
            headers: {
                'Accept': 'application/json'
            }
        });

        var result = null;
        try { result = await response.json(); } catch (e) { throw new Error('Failed to fetch canvas popup content'); }
        if (!result || !result.Success) throw new Error((result && result.Message) || 'Failed to fetch canvas popup content');
        return result.Data;
    }

    return {
        init: init,
        run: run,
        initPreview: initPreview,
        initAnnouncementPreview: initAnnouncementPreview,
    };
})();