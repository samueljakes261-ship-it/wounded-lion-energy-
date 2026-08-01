var errorPopupInterval;
let toTopBtnCont = '';
let webHdr = '';
let initialScrollY = 0;
let oldScrollY = window.scrollY;
let copyBtnClicked = false;
let bottomActiveNavItem = '';
let loaderBtnInnerHtml = '';
var _stParam = btoa(window.location.hostname);
function addCategoryIdToObj(obj, catId) {
    obj.CategoryId.push(catId);
}

function removeCategoryIdFromObj(obj, catId) {
    for (var i = 0; i < obj.CategoryId.length; i++) {
        if (obj.CategoryId[i] == catId) {
            obj.CategoryId.splice(i, 1);
            i--;
        }
    }
}

function addThemeToObj(obj, themeId) {
    obj.ThemeId.push(themeId);
}

function removeThemeFromObj(obj, themeId) {
    for (var i = 0; i < obj.ThemeId.length; i++) {
        if (obj.ThemeId[i] == themeId) {
            obj.ThemeId.splice(i, 1);
            i--;
        }
    }
}

function addTournamnetToObj(obj, tournamentId) {
    obj.TournamentId.push(tournamentId);
}

function removeTournamnetFromObj(obj, tournamentId) {
    for (var i = 0; i < obj.TournamentId.length; i++) {
        if (obj.TournamentId[i] == tournamentId) {
            obj.TournamentId.splice(i, 1);
            i--;
        }
    }
}

function changePageUrlWithoutRefreshing(url, stateId, replaceState) {
    PopupEngineModule.run();
    let searchParams = new URLSearchParams(url);
    let spHashData = searchParams.get('data');
    url = url.toLowerCase();

    if (spHashData != null && (url.includes('/sport') || url.includes('/esport'))) {
        url = url.replace(spHashData.toLowerCase(), spHashData);
    }
    if (typeof WBPLastUrl != 'undefined') {
        WBPLastUrl = url;
    }
    changeLanguageBarUrl(url);
    var origin = window.location.origin;
    url = origin + url;
    if (replaceState) {
        history.replaceState({ id: stateId }, null, url);
    } else {
        history.pushState({ id: stateId }, null, url);
    }

    if (typeof PopupEngineModule !== 'undefined' && typeof PopupEngineModule.run === 'function') {
        PopupEngineModule.run();
    }
}

function changeLanguageBarUrl(url) {
    let currentLang = document.documentElement.lang;
    let urlSplitted = url.split('/' + currentLang + '/');
    let urlWithoutLang = urlSplitted.length > 1 ? urlSplitted[1] : urlSplitted[0];
    if (urlWithoutLang.startsWith('/')) {
        urlWithoutLang = urlWithoutLang.substring(1);
    }
    let languageBarItems = document.querySelectorAll('.js_language_bar_link');
    if (languageBarItems.length > 0) {
        for (let item of languageBarItems) {
            let ln = item.dataset.lang;
            if (ln && ln != '') {
                
                if (item.href != undefined) {
                    item.href = '/' + ln + '/' + urlWithoutLang;
                } else if (item.value != undefined) {
                    item.value = '/' + ln + '/' + urlWithoutLang;
                }
            }
        }
    }
}

function CapitalizeText(txt) {
    return txt.charAt(0).toUpperCase() + txt.slice(1).toLowerCase();
}

function dlAnimate(html) {
    return $(html).css('opacity', '0').animate({ opacity: "1" }, 300);
}

function setStrFormatWithSpChar(s, char) {
    let betforeDot = '';
    let afterDot = '';
    if (s.includes('.')) {
        let splitedSt = s.split('.');
        betforeDot = splitedSt[0];
        afterDot = splitedSt[1];
    } else {
        betforeDot = s;
    }
    var str = reverseString(betforeDot);
    var returnStr = '';
    for (var i = 0; i < str.length; i++) {
        returnStr += str[i];
        if ((i + 1) % 3 == 0) {
            if (i + 1 != str.length) {
                returnStr += char;
            }
        }
    }
    if (afterDot != '') {
        return reverseString(returnStr) + '.' + afterDot;
    }
    return reverseString(returnStr);
}

function reverseString(s) {
    return s.split("").reverse().join("");
}

function setDataSrc(fItem) {
    let img = fItem.getElementsByTagName('img');
    if (img.length > 0) {
        let src = img[0].src;
        img[0].src = img[0].dataset.src;
        img[0].dataset.src = src;
    }
}

function setActiveClassToPrMenuItems(classname) {
    const ln = document.documentElement.getAttribute('lang');
    const links = document.getElementsByClassName(classname);
    const linksLength = links.length;
    const locationHrefSplitedByHost = document.location.href.split(document.location.host);
    const locationHref = locationHrefSplitedByHost.length > 1 ? locationHrefSplitedByHost[1].replace('/' + ln + '/', '/') : locationHrefSplitedByHost[0].replace('/' + ln + '/', '/');
    const lcnHrefSpBySlashLength = locationHref.split('/').length;
    let hrefSplited = '';
    let href = '';
    let correctActiveItem = '';
    let correctActiveItemLength = 0;
    let affectedItemsCount = 0;
    for (let i = 0; i < linksLength; i++) {
        links[i].classList.remove('tl_main_nav_item-active');
        if (links[i].href) {
            hrefSplited = links[i].href.split(document.location.host);
            if (hrefSplited.length > 1) {
                href = hrefSplited[1].replace('/' + ln + '/', '/')
                let firstPartWithoutWWW = hrefSplited[0].replace('www.', '');
                if (firstPartWithoutWWW.length > 8) {
                    if (!firstPartWithoutWWW.includes('playin') && !firstPartWithoutWWW.includes('sport'))
                        href = links[i].href;
                }
            } else {
                href = hrefSplited[0].replace('/' + ln + '/', '/');
            }

            switch (lcnHrefSpBySlashLength) {
                case 1:
                case 2:
                    if (locationHref.toLowerCase() == href.toLowerCase()) {
                        if (correctActiveItemLength < href.length) {
                            if (correctActiveItemLength != 0) {
                                removeActiveClassFromItem(correctActiveItem);
                            }
                            correctActiveItemLength = href.length;
                            correctActiveItem = links[i];
                        }
                        addActiveClassToItem(correctActiveItem);
                        affectedItemsCount++;
                    }
                    break;
                default:
                    if (locationHref.toLowerCase().startsWith(href.toLowerCase())) {
                        if (!locationHref.toLowerCase().includes('#') || (locationHref.toLowerCase().includes('#') && locationHref.toLowerCase() == href.toLowerCase())) {
                            if (correctActiveItemLength < href.length) {
                                if (correctActiveItemLength != 0) {
                                    removeActiveClassFromItem(correctActiveItem);
                                }
                                correctActiveItemLength = href.length;
                                correctActiveItem = links[i];
                            }
                            addActiveClassToItem(correctActiveItem);
                            affectedItemsCount++;
                        }
                    }
                    break;
            }
        }
    }
    return affectedItemsCount;
}

function addActiveClassToItem(item) {
    item.classList.add('tl_main_nav_item-active');
    let parentNode = item.parentNode.parentNode;
    if (parentNode && parentNode.classList.contains('js_header_dropdown')) {
        parentNode.firstElementChild.classList.add('tl_main_nav_item-active')
    }
    if (item.dataset.moreItem == 'true') {
        addClassIfElemExists('js_nav_more_toggle_btn', 'tl_main_nav_item-active');
    }
}

function removeActiveClassFromItem(item) {
    item.classList.remove('tl_main_nav_item-active');
    let parentNode = item.parentNode.parentNode;
    if (parentNode && parentNode.classList.contains('js_header_dropdown')) {
        parentNode.firstElementChild.classList.remove('tl_main_nav_item-active')
    }
    if (item.dataset.moreItem == 'true') {
        removeClassIfElemExists('js_nav_more_toggle_btn', 'tl_main_nav_item-active');
    }
}

function removeLangParamFromUrl(url) {
    let urlSplited = url.split('/')
    let returnVal = url;
    if (urlSplited.length > 1 && urlSplited[1].length == 2) {
        returnVal = '';
        for (let i = 2; i < urlSplited.length; i++) {
            returnVal += "/" + urlSplited[i];
        }
    }
    return returnVal;
}

function changeMetaTags(metaInfo, textToReplace) {
    let pageTitle = '';
    let metaTitleText = '';
    let metaDescText = '';
    let metaKeywordsText = '';

    if (typeof getCustomMetaTexts == 'function') {
        let metaTexts = getCustomMetaTexts();
        if (metaTexts.pageTitle && metaTexts.pageTitle != '') {
            pageTitle = metaTexts.pageTitle;
        }
        if (metaTexts.metaTitle && metaTexts.metaTitle != '') {
            metaTitleText = metaTexts.metaTitle;
        }
        if (metaTexts.metaDesc && metaTexts.metaDesc != '') {
            metaDescText = metaTexts.metaDesc;
        }
        if (metaTexts.metaKeywords && metaTexts.metaKeywords != '') {
            metaKeywordsText = metaTexts.metaKeywords;
        }
    } else if (typeof metaInfo === 'object') {
        if (metaInfo.title != undefined) {
            pageTitle = metaTitleText = metaInfo.title;

        }
        if (metaInfo.desc != undefined) {
            metaDescText = metaInfo.desc;
        }
        if (textToReplace != undefined) {
            pageTitle = metaTitleText = pageTitle.replace('{0}', textToReplace);
            metaDescText = metaDescText.replace('{0}', textToReplace);
        }
    } else {
        pageTitle = metaTitleText = metaDescText = metaKeywordsText = metaInfo;
    }

    if (pageTitle != '') {
        document.title = pageTitle;
    }
    if (metaTitleText != '') {
        let metaTitle = document.querySelector('meta[name="title"]');
        if (metaTitle != null) {
            metaTitle.setAttribute("content", metaTitleText);
        } else {
            let meta = document.createElement('meta');
            meta.setAttribute('name', 'title');
            meta.setAttribute('content', metaTitleText);
            document.getElementsByTagName('head')[0].appendChild(meta);
        }
    }
    if (metaDescText != '') {
        let metaDesc = document.querySelector('meta[name="description"]');
        if (metaDesc != null) {
            metaDesc.setAttribute("content", metaDescText);
        } else {
            let meta = document.createElement('meta');
            meta.setAttribute('name', 'description');
            meta.setAttribute('content', metaDescText);
            document.getElementsByTagName('head')[0].appendChild(meta);
        }
    }
    if (metaKeywordsText != '') {
        let metaKeywords = document.querySelector('meta[name="keywords"]');
        if (metaKeywords != null) {
            metaKeywords.setAttribute("content", metaKeywordsText);
        } else {
            let meta = document.createElement('meta');
            meta.setAttribute('name', 'keywords');
            meta.setAttribute('content', metaKeywordsText);
            document.getElementsByTagName('head')[0].appendChild(meta);
        }
    }
}

function changeOgXMetaTitleDesc(metaInfo, textToReplace) {
    let metaDesc = metaInfo.desc;
    let metaTitle = metaInfo.title;
    if (textToReplace != undefined) {
        metaDesc = metaDesc.replace('{0}', textToReplace);
        metaTitle = metaTitle.replace('{0}', textToReplace);
    }
    if (metaDesc != '') {
        let metaOgDesc = document.querySelector('meta[property="og:description"]');
        if (metaOgDesc != null) {
            metaOgDesc.setAttribute("content", metaDesc);
        } else {
            let meta = document.createElement('meta');
            meta.setAttribute('property', 'og:description');
            meta.setAttribute('content', metaDesc);
            document.getElementsByTagName('head')[0].appendChild(meta);
        }

        let metaXDesc = document.querySelector('meta[name="twitter:description"]');
        if (metaXDesc != null) {
            metaXDesc.setAttribute("content", metaDesc);
        } else {
            let meta = document.createElement('meta');
            meta.setAttribute('name', 'twitter:description');
            meta.setAttribute('content', metaDesc);
            document.getElementsByTagName('head')[0].appendChild(meta);
        }
    }

    if (metaTitle != '') {
        let metaOgTitle = document.querySelector('meta[property="og:title"]');
        if (metaOgTitle != null) {
            metaOgTitle.setAttribute("content", metaTitle);
        } else {
            let meta = document.createElement('meta');
            meta.setAttribute('property', 'og:title');
            meta.setAttribute('content', metaTitle);
            document.getElementsByTagName('head')[0].appendChild(meta);
        }

        let metaXTitle = document.querySelector('meta[name="twitter:title"]');
        if (metaXTitle != null) {
            metaXTitle.setAttribute("content", metaTitle);
        } else {
            let meta = document.createElement('meta');
            meta.setAttribute('name', 'twitter:title');
            meta.setAttribute('content', metaTitle);
            document.getElementsByTagName('head')[0].appendChild(meta);
        }
    }
}

function showInfoPopup(title, bodyMsg, btnName) {
    let btn = btnName != 'undefined' && btnName != '' ? btnName : 'Close';
    let html = `<div class="backdrop open" id="js_info_popup_cont"> <div class="join-popup"> <div class="join-popup__head"> <p class="join__head">${title}</p></div>` +
        `<div class="join-popup__body"> <p class="join__head">${bodyMsg}</p></div><div class="join-popup__footer">` +
        `<button data-role="none" class="btn-transparent" type="button" id="js_close_info_popup">${btn}</button></div></div></div>`;
    $('body').append(dlAnimate(html));
    document.body.classList.add('ofh')
}

function closeInfoPopup() {
    if (document.getElementById('js_info_popup_cont') != null) {
        document.getElementById('js_info_popup_cont').remove();
    }
    document.body.classList.remove('ofh')
}

function createToast(type, text, duration = 6000) {
    // Creating toast message container as dom element
    var toastElem = document.createElement("div");
    // Adding toast class to it
    toastElem.classList.add('toast');


    toastElem.id = 'js_toast_' + type;

    // If there is a type, add that type name as class to toast message container
    if (type) { toastElem.classList.add(type); }

    var iconType = "";
    if (type == "system") { iconType = '<i class="dynaimc_icon  cw_icon_info_v1 social__pointer-none"></i>'; }
    else if (type == "success") { iconType = '<i class="dynamic_icon cw_icon_check_v4 social__pointer-none"></i>'; }
    else if (type == "warning") { iconType = '<i class="dynamic_icon cw_icon_info_v1 social__pointer-none"></i>'; }
    else if (type == "error") { iconType = '<i class="dynamic_icon cw_icon_close_v5 social__pointer-none"></i>'; }

    toastElem.innerHTML = iconType;

    // create title dom element
    var titleElem = document.createElement("p");
    // add t-title class to doom element
    titleElem.classList.add('t-title');
    titleElem.classList.add('social__pointer-auto');

    // depent on the type add icon, you can add more icons if you want

    // appent icon to title element with title text
    titleElem.innerHTML += text;
    toastElem.appendChild(titleElem);

    // create text element with t-text class and appent text to it

    //var textElement = document.createElement("p");
    //textElement.classList.add('t-text');
    //textElement.innerHTML = text;
    //toastElem.appendChild(textElement);

    // create close element with t-close class for closing the toast message
    var closeElem = document.createElement("button");
    closeElem.classList.add('t-close');
    var iconX = document.createElement("i");
    iconX.classList.add("cw_icon_close_v2");
    iconX.classList.add("social__pointer-none");

    closeElem.appendChild(iconX);

    /*closeElem.classList.add('t-close');*/

    toastElem.appendChild(closeElem);

    // get toast-container element
    var toastContainer = document.getElementById("js-toast-cont");
    if (toastContainer == null) {
        toastContainer = document.createElement("div");
        toastContainer.classList.add("toast-container");
        toastContainer.id = "js-toast-cont";
        document.body.appendChild(toastContainer);
    }
    //appent toast message to it
    toastContainer.appendChild(toastElem);
    // wait just a bit to add active class to the message to trigger animation
    setTimeout(function () {
        toastElem.classList.add('active');
    }, 1);


    // check duration
    if (duration > 0) {
        // it it's bigger then 0 add it
        setTimeout(function () {
            toastElem.classList.remove('active');
            setTimeout(function () {
                toastElem.remove();
            }, 350);
        }, duration);
    } else if (duration == null) {
        //  it ther isn't any add default one (3000ms)
        setTimeout(function () {
            toastElem.classList.remove('active');
            setTimeout(function () {
                toastElem.remove();
            }, 350);
        }, 3000);
    }
    //if duration is 0, toast message will not be closed
}

function playAndMuteBannerVideo(sliderWrapperElem, disableAutoplay) {

    let videoElems = $(sliderWrapperElem).find('video');
    let slider = '';
    if (typeof $(sliderWrapperElem).parents('.swiper-initialized')[0].swiper != 'undefined') {
        slider = $(sliderWrapperElem).parents('.swiper-initialized')[0].swiper;
    }

    if (videoElems) {
        if (slider != '' && !disableAutoplay) {
            slider.autoplay.start();
        }
        for (let i = 0; i < videoElems.length; i++) {
            if (videoElems[i]) {
                videoElems[i].muted = true;
                $(videoElems[i]).siblings('.js_voice_icon').addClass('muted');
            }
        }
    }
}

let videoBannersObserver = new IntersectionObserver(function (entries) {
    entries.forEach((entry) => {
        if (entry.target.tagName == 'VIDEO') {
            if (entry.isIntersecting) {
                entry.target.play();
            } else {
                entry.target.pause();
            }
        } else {
            let videos = entry.target.querySelectorAll('video');
            if (videos.length > 0) {
                if (entry.isIntersecting) {
                    videos.forEach(video => { video.play() });
                } else {
                    videos.forEach(video => { video.pause() });
                }
            }
        }
    });
}, { threshold: [0.4] });

function addToVideoBannersObserver(contId, addContainer) {
    let elem = document.getElementById(contId);
    if (addContainer) {
        videoBannersObserver.observe(elem);
    } else {
        let videos = elem.querySelectorAll('video');
        videos.forEach(video => { videoBannersObserver.observe(video) });
    }
}
function showSoundIconIfVideoHasAudio(elem) {
    setTimeout(() => {
        let hasAudioTrack = false;
        if (elem.audioTracks && elem.audioTracks.length > 0) {
            for (let i = 0; i < elem.audioTracks.length; i++) {
                if (elem.audioTracks[i].enabled) {
                    hasAudioTrack = true;
                    break;
                }
            }
        } else if (elem.webkitAudioDecodedByteCount > 0 || elem.mozHasAudio) {
            hasAudioTrack = true;
        }
        if (hasAudioTrack && elem.nextElementSibling) {
            elem.nextElementSibling.classList.remove('hidden');
        }
    }, 300);
}
function customPauseResumeTimer(callback, delay) {
    let timerId;
    let start;
    let remaining = delay;

    this.pause = function () {
        window.clearTimeout(timerId);
        timerId = null;
        remaining -= Date.now() - start;
    };
    this.resume = function () {
        if (timerId) {
            return;
        }

        start = Date.now();
        timerId = window.setTimeout(callback, remaining);
    };
    this.cancel = function () {
        window.clearTimeout(timerId);
    };
    this.resume();
};

function initPresslHoldEvent(item, holdStart, holdEnd, click) {
    let timerID;
    let counter = 0;
    let allowDispatchStart = true;
    let pressHoldEventStart = new CustomEvent("pressHoldStart");
    let pressHoldEventEnd = new CustomEvent("pressHoldEnd");
    let customClick = new CustomEvent("customClick");
    let typeOfClick = typeof click;
    let pressHoldDuration = 10;
    let touchStartClientX = '';

    item.addEventListener("mousedown", pressingDown, false);
    item.addEventListener("mouseup", notPressingDown, false);
    item.addEventListener("mouseleave", notPressingDown, false);

    item.addEventListener("touchstart", pressingDown, false);
    item.addEventListener("touchend", notPressingDown, false);

    if (typeof holdStart == 'function') {
        item.addEventListener("pressHoldStart", holdStart, false);
    }
    if (typeof holdEnd == 'function') {
        item.addEventListener("pressHoldEnd", holdEnd, false);
    }
    if (typeOfClick == 'function') {
        item.addEventListener("customClick", click, false);
    }

    function pressingDown(e) {
        if (typeOfClick == 'function') {
            if (e.type == 'touchstart') {
                touchStartClientX = e.touches[0].clientX;
            } else {
                touchStartClientX = e.clientX;
            }
        }

        if (e.type == 'mousedown' || (e.type == 'touchstart' && e.touches.length == 1)) {
            requestAnimationFrame(timer);
            e.preventDefault();
        }
    }

    function notPressingDown(e) {
        allowDispatchStart = true;
        cancelAnimationFrame(timerID);
        if (counter < pressHoldDuration) {
            if (typeOfClick == 'function') {
                if (e.type == 'touchend') {
                    customClick.clientX = e.changedTouches[0].clientX;
                } else {
                    customClick.clientX = e.clientX;
                }
                customClick.passedTarget = e.target;
                if (Math.abs(touchStartClientX - customClick.clientX) < 5) {
                    item.dispatchEvent(customClick);
                }
            }
        } else {
            item.dispatchEvent(pressHoldEventEnd);
        }
        counter = 0;
    }

    function timer() {
        timerID = requestAnimationFrame(timer);
        counter++;
        if (counter >= pressHoldDuration && allowDispatchStart) {
            allowDispatchStart = false;
            item.dispatchEvent(pressHoldEventStart);
        }
    }
}

async function writeToClipboard(txt) {
    try {
        if (typeof CwPwapp != 'undefined' && CwPwapp) {
            if (navigator.clipboard) {
                await navigator.clipboard.writeText(txt);
            }
            let w = window.parent || window;
            await w.postMessage({ type: 'cw_copy', data: { text: txt } }, '*');
        } else {
            await navigator.clipboard.writeText(txt);
        }
    } catch (err) {
        console.error('Failed to copy: ', err);
    }
}

function openYoutubeVideo(link) {
    if (document.getElementById('js_ytb_video_cont') == null) {
        $('body').append('<div id="js_ytb_video_cont" style="display: none;" class="youtube_banner"></div>');
    }

    $('#js_ytb_video_cont').html('<div class="tl_head_close js_close_ytb_popup close_youtube_banner transition200ms"></div><iframe width="100%" height="100%" src="' + link + '?autoplay=1"></iframe>').show();
}

function handleDocumentScroll() {
    if (toTopBtnCont != null && toTopBtnCont != '') {
        if (window.scrollY > 300) {
            if (oldScrollY > window.scrollY) {
                toTopBtnCont.classList.remove('hidden');
            } else {
                toTopBtnCont.classList.add('hidden');
            }
        } else {
            toTopBtnCont.classList.add('hidden');
        }
        oldScrollY = window.scrollY;
    }
    if (webHdr != null && webHdr != '') {
        if (window.scrollY > 54) {
            webHdr.classList.add('fixed_head');
        } else {
            webHdr.classList.remove('fixed_head');
        }
    }
    if (document.querySelector('.js_jacpkpots_cont[data-view-type="web"]') && document.querySelectorAll('.js_jacpkpots').length > 0) {
        setJackpotHoverPosition();
    }
    if (document.documentElement.dataset.type == 'Mobile' && document.documentElement.dataset.stickyHeader == 'True') {
        handleMobileHeaderNavBarAppearance();
    }
}

function handleMobileHeaderNavBarAppearance() {
    if (document.readyState == 'complete') {
        let scY = window.scrollY;
        if (initialScrollY >= scY) {
            document.documentElement.classList.remove('hide_header_navbar');
        } else if (initialScrollY > 5) {
            document.documentElement.classList.add('hide_header_navbar');
        }
        initialScrollY = scY;
    }
}

function getUrlPathQueryHash() {
    let url = document.location.href.split(document.location.host);
    if (url.length > 0) {
        return url[1];
    }
    return document.location.pathname;
}

function setDatePickerValues() {
    const period = Number(document.getElementById('js_filter_period').value);
    const from = document.getElementById('js_filter_from');
    const to = document.getElementById('js_filter_to');
    from.setAttribute('readonly', true);
    to.setAttribute('readonly', true);
    switch (period) {
        case 1:
            from.value = formatDate(addDays(new Date(), -1));
            to.value = formatDate(addDays(new Date(), 0));
            break;
        case 2:
            from.value = formatDate(addDays(new Date(), -7));
            to.value = formatDate(addDays(new Date(), 0));
            break;
        case 3:
            from.value = formatDate(addDays(new Date(), -14));
            to.value = formatDate(addDays(new Date(), 0));
            break;
        case 4:
            from.value = formatDate(addDays(new Date(), -30));
            to.value = formatDate(addDays(new Date(), 0));
            break;
        case 5:
            from.removeAttribute('readonly');
            to.removeAttribute('readonly');
            break;
    }
}

function addDays(date, days) {
    date.setDate(date.getDate() + days);
    return date;
}

function formatDate(date) {
    let d = new Date(date),
        month = '' + (d.getMonth() + 1),
        day = '' + d.getDate(),
        year = d.getFullYear();

    if (month.length < 2)
        month = '0' + month;
    if (day.length < 2)
        day = '0' + day;
    return [year, month, day].join('-');
}

function checkFromToDates(elem) {
    const from = document.getElementById('js_filter_from');
    const to = document.getElementById('js_filter_to');
    
    var datePartsStart = (from.value).split('-');
    var datePartsEnd = (to.value).split('-');
    
    // Reorder the date parts to MM/DD/YYYY
    var formattedDateStart = datePartsStart[1] + '/' + datePartsStart[2] + '/' + datePartsStart[0];
    var formattedDateEnd = datePartsEnd[1] + '/' + datePartsEnd[2] + '/' + datePartsEnd[0];

    var Date_Dtart = new Date(formattedDateStart);
    var Date_End = new Date(formattedDateEnd);

    var timeDifference = Date_End - Date_Dtart;

    // Convert time difference from milliseconds to days
    var daysDifference = timeDifference / (1000 * 3600 * 24);

    if (from.value == '' || to.value == '' || new Date(from.value) > new Date(to.value)) {
        switch (elem.name) {
            case 'From':
                from.value = to.value
                break;
            case 'To':
                to.value = from.value
                break;
        }
        createToast('error', 'From date cannot be greater than the To date', 4000);
        return false;
    } else if (daysDifference > 90) {
        createToast('error', $("#js_ThreeMonthMessage").val(), 4000);
        return false;
    }
    return true;
}

function loaderInsideShowHide(buttonId, show) {
    let btn = document.getElementById(buttonId);
    if (btn) {
        let lInside = btn.querySelector('#js_loader_inside');
        let lReplace = btn.querySelector('#js_loading_replace');
        if (lInside && lReplace) {
            lInside.style.display = show ? 'block' : 'none';
            lReplace.style.display = show ? 'none' : 'block';
        }
    }
}

function getCss(name) {
    if (document.querySelector('link[href="' + name + '"]') != null) {
        return Promise.resolve();
    }
    return new Promise((resolve, reject) => {
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = name;
        link.onload = () => resolve();
        link.onerror = () => resolve();
        document.head.appendChild(link);
    });
}

function startEgtJackBorderAnim(cdnUrl, speed) {
    let jackpotsCont = document.getElementsByClassName('js_jacpkpots');
    for (let i = 0; i < 4; i++) {
        jackpotsCont[i].style.backgroundImage = 'url(' + cdnUrl + 'Img/icons/redesign/jackpot_backgr.png)';
    }

    function jackpotAnim(elnum) {
        let jackpotAnimPos = 0;
        let jackpotAnimInt = setInterval(function () {
            jackpotsCont[elnum].style.backgroundPosition = '0px -' + jackpotAnimPos + 'px';
            jackpotAnimPos = jackpotAnimPos + 92.6;
            if (jackpotAnimPos > 2500) {
                clearInterval(jackpotAnimInt);
            }
        }, speed);
    }

    for (var i = 0; i < 4; i++) {
        (function (i) {
            setTimeout(function () { jackpotAnim(i) }, i * 400);
        })(i);
    }

}

function CheckClientCashback() {
    return $.ajax({
        url: "/Account/CheckCashback",
        type: "GET",
        datatype: "json",
        success: function (result) {
            if (result && result != '') {
                $('body').append(result).addClass('ofh');
            }
        }
    });
}

function BetSharePopup(betId) {
    return $.ajax({
        url: "/account/getbetdetailsforshare",
        type: "GET",
        data: { BetId: betId },
        datatype: "json",
        success: function (result) {
            if (result && result != '') {
                $('body').append(result).addClass('ofh');
            }
        }
    });
}

function ShareBet(data) {
    $.ajax({
        url: "/account/sharebet",
        type: "POST",
        contentType: "application/json; charset=utf-8",
        data: JSON.stringify(data),
        dataType: "json",
        success: function (result) {
            if (result.Success && result.ShareToken != '') {
                showHideButtonLoader('js_save_share_bet_btn', false);
                var shareData = {
                    title: 'Bet Share',
                    text: '',
                    url: `https://${result.UrlDomain}?sharetoken=${result.ShareToken}`
                };

                if (!navigator.share) {
                    createToast('error', 'Web Share API is not supported in this browser.');
                    return;
                }
                if (!navigator.canShare || navigator.canShare(shareData)) {
                    try {
                        navigator.share(shareData);
                    } catch (error) {
                        createToast('error', `Sharing failed or was cancelled: ${error.message}`);
                    }
                } else {
                    createToast('error', 'The specified data format cannot be shared.');
                }
            }
        }
    });
}

function GetSharedBetDetails(token) {

    return $.ajax({
        url: "/home/getsharedbetdetails",
        type: "GET",
        data: { ShareToken: token },
        datatype: "json",
        success: function (result) {
            if (result && result != '') {
                $('body').append(result).addClass('ofh');
            }
        }
    });
}

function showHideLoader(show) {
    if (show) {
        if (typeof showSpinner === 'function') {
            showSpinner();
        }
    } else {
        if (typeof hideSpinner === 'function') {
            hideSpinner();
        }
    }
}

function toggleLeftSidebar() {

    if (document.body.classList.contains('cw_mob_root-sidebar_opened')) {
        closeLeftSideBar();
    } else {
        openLeftSideBar();
    }
}

function openLeftSideBar() {
    if (document.body.classList.contains('cw_mob_root-right_sidebar_opened')) {
        closeRightSidebar();
    }
    handleBottomActiveNavItemStateChange(true, 'js_nav_left_toggle_btn');
    document.body.classList.add('cw_mob_root-sidebar_opened');
    document.body.style.overflow = 'hidden';
    $('#js_to_top_cont').css('z-index', '0');
}

function closeLeftSideBar() {
    handleBottomActiveNavItemStateChange(false, 'js_nav_left_toggle_btn');
    document.body.classList.remove('cw_mob_root-sidebar_opened');
    document.body.removeAttribute('style');
    $('#js_to_top_cont').removeAttr('style');
}

function toggleRightSidebar(openBalance) {
   
    if (document.body.classList.contains('cw_mob_root-right_sidebar_opened')) {
        closeRightSidebar();
    } else {
        openRightSidebar(openBalance);
    }
}

function openRightSidebar(openBalance) {

    if (document.getElementById('js_login_sidebar_cont') == null) {
        handleRightSideBarVisibility(openBalance);
    } else {
        $.ajax({
            url: "/login/loginpartial",
            type: "POST",
            success: function (result) {
                $('#js_login_sidebar_cont').html(result);
            },
            error: function (xhr, status, error) {
                if (xhr.getResponseHeader('cf-mitigated') === 'challenge') {    
                    location.href = '/login/loginpartial?p=true';
                }
            }
        }).then(() => {
            handleRightSideBarVisibility(openBalance);
        });
    }
}
function handleRightSideBarVisibility(openBalance) {
    if (document.body.classList.contains('cw_mob_root-sidebar_opened')) {
        closeLeftSideBar();
    }
    handleBottomActiveNavItemStateChange(true, 'js_nav_right_toggle_btn');
    document.body.classList.add('cw_mob_root-right_sidebar_opened');
    document.body.style.overflow = 'hidden';
    $('#js_to_top_cont').css('z-index', '0');

    openBalance && $('.js_balance_content .js_balances').trigger('click');
}
function closeRightSidebar() {
    handleBottomActiveNavItemStateChange(false, 'js_nav_right_toggle_btn');
    document.body.classList.remove('cw_mob_root-right_sidebar_opened');
    document.body.removeAttribute('style');
    $('#js_to_top_cont').removeAttr('style');

    //$(".balance__slider").hasClass("opened") && $('.js_balance_content .js_balances').trigger('click');
}

function handleBottomActiveNavItemStateChange(open, toggleBtnId) {
    let togglebtn = document.getElementById(toggleBtnId);
    let lgBtn = document.getElementById('js_mob_sign_in');
    if (open) {
        let bmNavItem = document.querySelectorAll('.js_bm_nav_items');
        if (togglebtn) {
            if (togglebtn.classList.contains('tl_main_nav_item-active')) {
                togglebtn.dataset.keepActiveClass = 'true';
            } else {
                for (var i = 0; i < bmNavItem.length; i++) {
                    if (bmNavItem[i].classList.contains('tl_main_nav_item-active')) {
                        bottomActiveNavItem = bmNavItem[i];
                    }
                }
                togglebtn.classList.add('tl_main_nav_item-active');
                togglebtn.dataset.keepActiveClass = 'false';
            }
        }
        if (lgBtn) {
            document.body.classList.add('login_sidebar');
        }

        if (typeof bottomActiveNavItem == 'object') {
            bottomActiveNavItem.classList.remove('tl_main_nav_item-active');
            if (bottomActiveNavItem.dataset.moreItem == 'true') {
                removeClassIfElemExists('js_nav_more_toggle_btn', 'tl_main_nav_item-active');
            }
        }
    } else {
        if (typeof bottomActiveNavItem == 'object') {
            bottomActiveNavItem.classList.add('tl_main_nav_item-active');
            if (bottomActiveNavItem.dataset.moreItem == 'true') {
                addClassIfElemExists('js_nav_more_toggle_btn', 'tl_main_nav_item-active');
            }
            if (bottomActiveNavItem.id == 'js_nav_right_toggle_btn' || bottomActiveNavItem.id == 'js_nav_left_toggle_btn') {
                bottomActiveNavItem = '';
            }
        }
        if (togglebtn && togglebtn.dataset.keepActiveClass != 'true') {
            togglebtn.classList.remove('tl_main_nav_item-active');
        }
        if (lgBtn) {
            document.body.classList.remove('login_sidebar');
        }
    }
}

function hideBottomNavBar() {
    document.body.classList.add('without_navbar');
    document.getElementById('js_bn_nav_bar').classList.add('cw_mob_mav_fixed_bot_hide');
}

function showBottomNavBar() {
    document.body.classList.remove('without_navbar');
    document.getElementById('js_bn_nav_bar').classList.remove('cw_mob_mav_fixed_bot_hide');
}

function handleSpAppEventDispatch(data, setActiveClass) {
    if (data) {
        switch (data.type) {
            case 3:
                if (data.message && data.message.path) {

                    switch (data.message.path.toLowerCase()) {
                        case '/bet-history':
                        case '/chat':
                            hideBottomNavBar();
                            break;
                        case '/live':
                            showBottomNavBar();
                            if (setActiveClass) {
                                setSpActiveClassToNavBar('live');
                            }
                            break;
                        case '/pre-match':
                            showBottomNavBar();
                            if (setActiveClass) {
                                setSpActiveClassToNavBar('prematch');
                            }
                            break;
                        case '/event-details':
                            showBottomNavBar();
                            if (setActiveClass) {
                                if (data.message.qs) {
                                    setSpActiveClassToNavBar(data.message.qs.isLive == '0' ? 'prematch' : 'live');
                                }
                            }
                            break;
                        case '/':
                            showBottomNavBar();
                            if (setActiveClass) {
                                setSpActiveClassToNavBar('sport');
                            }
                            break;
                        default:
                            showBottomNavBar();
                            break;
                    }
                }
                break;
            default:
                showBottomNavBar();
                break;
        }
    }
}

function setSpActiveClassToNavBar(page) {
    let navBarItems = document.querySelectorAll('.js_bm_nav_items');
    let navBarItemsLength = navBarItems.length;
    let urlFound = false;
    let fundUrlCount = 0;
    for (let i = 0; i < navBarItemsLength; i++) {
        if (navBarItems[i].href) {
            urlFound = page == 'sport' ? navBarItems[i].href.toLowerCase().endsWith('/sport') || navBarItems[i].href.toLowerCase().endsWith('/sport/reactindex') :
                navBarItems[i].href.toLowerCase().endsWith('/sport/live') || navBarItems[i].href.toLowerCase().endsWith('#live/page') || navBarItems[i].href.toLowerCase().endsWith('#live');
            urlFound = page == 'prematch' ? navBarItems[i].href.toLowerCase().endsWith('/sport/prematch') || navBarItems[i].href.toLowerCase().endsWith('/sport/pre-match') || navBarItems[i].href.toLowerCase().endsWith('#pre-match') : urlFound
        }
        navBarItems[i].classList.remove('tl_main_nav_item-active');
        if (urlFound && fundUrlCount == 0) {
            fundUrlCount++;
            navBarItems[i].classList.add('tl_main_nav_item-active');
        }
    }
}

function addClassIfElemExists(elemId, className) {
    let elem = document.getElementById(elemId);
    if (elem) {
        elem.classList.add(className);
    }
}

function removeClassIfElemExists(elemId, className) {
    let elem = document.getElementById(elemId);
    if (elem) {
        elem.classList.remove(className);
    }
}

function setActiveClassToLeftOrRightNavButton(href, isLeftBtnDefaultActive) {
    if (href.includes('/account') || href.includes('/bonus') || href.includes('/referafriend') || href.includes('/responsiblegaming') || href.includes('/agent')) {
        addClassIfElemExists('js_nav_right_toggle_btn', 'tl_main_nav_item-active');
    } else if (isLeftBtnDefaultActive) {
        addClassIfElemExists('js_nav_left_toggle_btn', 'tl_main_nav_item-active');
    }
}

function setCookie(cname, cvalue, exdays, domain) {
    var d = new Date();
    d.setTime(d.getTime() + (exdays * 24 * 60 * 60 * 1000));
    var expires = "expires=" + d.toGMTString();
    if (typeof domain != 'undefined' && domain != '') {
        document.cookie = cname + "=" + cvalue + ";" + expires + ";path=/;domain=" + domain;
    } else {
        document.cookie = cname + "=" + cvalue + ";" + expires + ";path=/";
    }
}

function getCookie(cname) {
    var name = cname + "=";
    var decodedCookie = decodeURIComponent(document.cookie);
    var ca = decodedCookie.split(';');
    for (var i = 0; i < ca.length; i++) {
        var c = ca[i];
        while (c.charAt(0) == ' ') {
            c = c.substring(1);
        }
        if (c.indexOf(name) == 0) {
            return c.substring(name.length, c.length);
        }
    }
    return "";
}

function skeletOn(type, count, contId) {
    let html = '';
    switch (type) {
        case 'jackpot':
            html = ` <div class="skeleton-jackpot__container">`;
            for (let i = 0; i < count; i++) {
                html += `<div class="skeleton-jackpot__body"><div class="skeleton-jackpot__icon skeleton"></div><div class="skeleton-jackpot__content">` +
                    `<div class="skeleton-jackpot__value skeleton"></div></div></div>`;
            }
            html += `</div>`;
            break;
    }
    $(contId).html(html);
}

function skeletOff(type) {
    switch (type) {
        case 'topwins':
            $('#js_top_winers_skelet').remove();
            break;
    }
}
function getCurrentPage() {
    _stParam = btoa(window.location.hostname);
    return _stParam;
}
function handleBalancesVisibility() {
    if (window.js_mw_sport_balances != undefined) {
        let isVisCashbackBalance = window.CashbackBalancePanel && !window.CashbackBalancePanel.classList.contains('dis_none');
        let isVisSpTournamentBalance = window.TournamentBalancePanel && !window.TournamentBalancePanel.classList.contains('dis_none');
        let isVisSpBonusBalance = window.SportBonusPanel && !window.SportBonusPanel.classList.contains('dis_none');
        if (!isVisCashbackBalance || isVisSpTournamentBalance || isVisSpBonusBalance) {
            window.js_mw_sport_balances.style.display = "block";
        } else {
            window.js_mw_sport_balances.style.display = "none";
        }
    } else if (window.js_balance_content != undefined && !window.js_balance_content.classList.contains('js_balance_content')) {
        let isVisBonusBalance = window.bonusBalanceCont && !window.bonusBalanceCont.classList.contains('hidden');
        let isVisCashbackBalance = window.CashbackBalancePanel && !window.CashbackBalancePanel.classList.contains('dis_none');
        let isVisSpTournamentBalance = window.TournamentBalancePanel && !window.TournamentBalancePanel.classList.contains('dis_none');
        let isVisSpBonusBalance = window.SportBonusPanel && !window.SportBonusPanel.classList.contains('dis_none');
        if (isVisBonusBalance || isVisCashbackBalance || isVisSpTournamentBalance || isVisSpBonusBalance) {
            window.js_balance_content.classList.add('js_balance_content');
            window.js_balances_ddwn.classList.add('js_balances');
            window.js_balances_ddwn_arrow.classList.remove('hidden');
        } else {
            window.js_balance_content.classList.remove('js_balance_content');
            window.js_balances_ddwn.classList.remove('js_balances');
            window.js_balances_ddwn_arrow.classList.add('hidden');
        }
    }
}

function showHideButtonLoader(btnId, show) {
    let btn = document.getElementById(btnId);
    let fontSize = 36;
    if (btn) {
        if (show) {
            btn.style.pointerEvents = 'none';
            fontSize = btn.dataset.loaderFontSize != undefined ? btn.dataset.loaderFontSize : 36;
            btn.style.minWidth = btn.getBoundingClientRect().width + 'px';
            loaderBtnInnerHtml = btn.innerHTML;
            btn.innerHTML = `<span class="loading-dots" style="font-size:${fontSize}px;"><span style="--index:0"></span><span style="--index:1"></span><span style="--index:2"></span>` +
                `<span style="--index:3"></span><span style="--index:4"></span><span style="--index:5"></span><span style="--index:6"></span><span style="--index:7"></span>` +
                `<span style="--index:7"></span><span style="--index:8"></span><span style="--index:9"></span></span>`;
        } else {
            btn.style.minWidth = '';
            btn.style.pointerEvents = '';
            if (loaderBtnInnerHtml != '') {
                btn.innerHTML = loaderBtnInnerHtml;
            }
        }
    }
}

function setJackpotHoverPosition() {
    let scrolledval = $(window).scrollTop();
    let needScrollVal = $('.top_jackpots__block').offset().top - ($(window).height() / 2);
    if (scrolledval > needScrollVal) {
        $('.top_jackpots__hover_block').css({ 'bottom': 'auto', 'top': '100%' })
    } else {
        $('.top_jackpots__hover_block').css({ 'bottom': '100%', 'top': 'auto' })
    }
}

function showHideMoreMenu(show) {
    if (show) {
        $('#js_nav_more_toggle_btn').addClass('opened_menu')
        $('#js_more_content').addClass('opened_circle');
    } else {
        $('#js_nav_more_toggle_btn').removeClass('opened_menu')
        $('#js_more_content').removeClass('opened_circle');
    }
}

function hasLoginButton(html) {
    let btns = $(html).find('.loginDialog');
    if (btns.length > 0) {
        return true;
    }
    btns = $(html).find('#js_mob_sign_in');
    if (btns.length > 0) {
        return true;
    }
    return false;
}

function parentsNative(el, selector) {
    const parents = [];
    while ((el = el.parentNode) && el !== document) {
        if (!selector || el.matches(selector)) parents.push(el);
    }
    return parents;
}

function isElemOrChildrenSameAsTarget(elemSelector, target) {
    if (target.matches(elemSelector)) {
        return true;
    }
    let returnVal = false;
    let parents = parentsNative(target, elemSelector);
    if (parents.length > 0) {
        parents.forEach((p) => {
            if (p.matches(elemSelector)) {
                returnVal = true;
            }
        });
    }
    return returnVal;
}
let allowCashierPopup = true;
function openCashierPopup(pmType, amount = '') {
    if (document.body.classList.contains('cw_mob_root-right_sidebar_opened')) {
        closeRightSidebar();
    }
    if (allowCashierPopup) {
        allowCashierPopup = false;
        if (pmType != 1 && pmType != 2) {
            return;
        }
        showHideLoader(true);
        $('body').addClass('ofh');
        $.ajax({
            url: "/Account/GetPaymentByCashier",
            type: "POST",
            datatype: "json",
            data: { paymentType: pmType, currentPath: document.location.pathname, amount: amount },
            success: function (result) {
                
                $('body').append(result);
                showHideLoader(false);
                allowCashierPopup = true;
            },
        });
    }
}

function closeCashierPopup() {
    let cash_popup = $('body').find('.js_cashier_wrapper');
    if (cash_popup) {
        if (typeof click != 'undefined') {
            click = 0;
        }

        if (cash_popup.attr("depositLeave") != undefined && window.dataLayer) {
            window.dataLayer.push({
                'event': 'deposit_page_leave',
                'event_category': 'deposit'
            });
        }

        $(cash_popup).remove();
        $('body').removeClass('ofh');       
        showHideLoader(false);

        let url = window.location.href.toLowerCase();
        if (url.includes('?deposit=1')) {
            url = url.replace('?deposit=1', '');
            history.replaceState({ id: '' }, '', url);
            if (typeof changeLanguageBarUrl == 'function') {
                let currentLang = document.documentElement.lang;
                let isLnInUrl = url.split('/' + currentLang + '/').length > 1;
                changeLanguageBarUrl(isLnInUrl ? '/' + currentLang + '/' : '/');
            }
        };
    }
}
let allowBnReqPopup = true;
function openBonusRequestPopup(fromWeb, fromTab) {
    if (document.body.classList.contains('cw_mob_root-right_sidebar_opened')) {
        closeRightSidebar();
    }
    if (allowBnReqPopup && allowCashierPopup) {
        allowBnReqPopup = false;
        showHideLoader(true);
        if (!$('body').hasClass('ofh')) {
            $('body').addClass('ofh');
        }
        $.ajax({
            url: "/Bonus/GetBonusRequest",
            type: "POST",
            datatype: "json",
            success: function (result) {
                if (result == 0) {
                    if (fromWeb) {
                        if (fromTab) {
                            loadTab('deposit_tab', "/Account/Deposit", function () {
                                activateTab('deposit_tab');
                            });
                        } else {
                            showAccountPopup('/Account/Deposit', 'deposit_tab', {
                                width: 1600,
                                height: 681,
                            });
                        }
                        allowBnReqPopup = true;
                    }
                    else {
                        $.ajax({
                            url: "/Account/IsPaymentsByCashier",
                            type: "POST",
                            datatype: "json",
                            success: function (result) {
                                if (result == "True") {
                                    openCashierPopup(1);
                                }
                                else {
                                    document.location.href = "/account/deposit";
                                }
                                allowBnReqPopup = true;
                            },
                        });
                    }
                } else {
                    $('body').append(result);
                    allowBnReqPopup = true;
                }
                showHideLoader(false);
            }
        });
    }
}

function openDepositFromBnReqPopup(bonusId, rewardType) {
    showHideLoader(true);
    $.ajax({
        url: "/Account/Deposit",
        type: "POST",
        datatype: "json",
        data: { bonusId: bonusId, depWithoutReward: rewardType },
        success: function (result) {
            $('body').append(result).addClass('ofh');
            showHideLoader(false);
        }
    });
}

function openLogoutConfPopup() {  
    showHideLoader(true);
    $.ajax({
        url: "/Account/ConfirmLogout",
        success: function (result) {
            $('body').append(result).addClass('ofh');
            showHideLoader(false);
        }
    });
}


function openRegCloseConfPopup() {
    showHideLoader(true);
    window.allowOpenRegCloseConfirmPopup = false;
    $.ajax({
        url: "/Registration/ConfirmRegClose",
        success: function (result) {
            $('body').append(result);
            showHideLoader(false);
        }
    });
}

function closeAllNativeSelects() {
    const selects = document.querySelectorAll('select');
    selects.forEach(select => {
        select.blur();
    });
}

if (!String.prototype.format) {
    String.prototype.format = function () {
        var args = arguments;
        return this.replace(/{(\d+)}/g, function (match, number) {
            return typeof args[number] != 'undefined' ? args[number] : match;
        });
    };
}

function updateMetaTags(newMeta) {

    if (newMeta.title) {
        document.title = newMeta.title;

        let titleTag = document.querySelector("title");
        if (!titleTag) {
            titleTag = document.createElement("title");
            document.head.appendChild(titleTag);
        }
        titleTag.textContent = newMeta.title;
    }

    if (newMeta.canonical) {
        let canonicalTag = document.head.querySelector('link[rel="canonical"]');
        if (!canonicalTag) {
            canonicalTag = document.createElement('link');
            canonicalTag.setAttribute('rel', 'canonical');
            document.head.appendChild(canonicalTag);
        }
        canonicalTag.setAttribute('href', newMeta.canonical);
    }

    function setMetaTag(name, content, attrName = "name") {
        let meta = document.querySelector(`meta[${attrName}="${name}"]`);
        if (!meta) {
            meta = document.createElement("meta");
            meta.setAttribute(attrName, name);
            document.head.appendChild(meta);
        }
        meta.setAttribute("content", content);
    }

    if (newMeta.description) setMetaTag("description", newMeta.description);
    if (newMeta.keywords) setMetaTag("keywords", newMeta.keywords);
    if (newMeta.metaTitle) setMetaTag("title", newMeta.metaTitle);


    if (newMeta.ogTitle) setMetaTag("og:title", newMeta.ogTitle, "property");
    if (newMeta.ogDescription) setMetaTag("og:description", newMeta.ogDescription, "property");
    if (newMeta.ogUrl) setMetaTag("og:url", newMeta.ogUrl, "property");

    if (newMeta.twitterTitle) setMetaTag("twitter:title", newMeta.twitterTitle);
    if (newMeta.twitterDescription) setMetaTag("twitter:description", newMeta.twitterDescription);

}

const _loadedScripts = new Set();
function loadScriptOnce(src, callback) {
    if (_loadedScripts.has(src)) {
        if (callback) {
            callback();
        }
        return;
    }
    _loadedScripts.add(src);
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    if (callback) {
        script.onload = callback;
    }
    script.onerror = function () {
        console.warn('Failed to load script ' + src);
    };
    document.head.appendChild(script);
}

const _loadedStyles = new Set();

function loadCssOnce(href) {
    if (_loadedStyles.has(href)) {
        return;
    }
    _loadedStyles.add(href);
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    document.head.appendChild(link);
}

function waitForJs(callback, objName) {
    let attempts = 0;
    const interval = setInterval(() => {
        if (typeof window[objName] != 'undefined') {
            clearInterval(interval);
            callback();
        } else if (attempts >= 10) {
            clearInterval(interval);
        }
        attempts++;
    }, 300);
};

document.addEventListener('click', function (e) {
    //check is the right element clicked
    if (!e.target.matches('.t-close')) return;
    else {
        //get toast element
        var toastElement = e.target.parentElement;
        // remove active class from it to trigger css animation with duration of 300ms
        toastElement.classList.remove('active');
        //wait for 350ms and then remove element
        setTimeout(function () {
            toastElement.remove();
        }, 350);
    }
});

$(document).on('click', '#js_close_err_popup', function () {
    clearInterval(errorPopupInterval);
    $('#js_error_popup').remove();
});

$(document).on('click', '.js_banner_video_link', function (e) {

    if ($(e.target).hasClass('js_voice_icon') || $(e.target).parents().hasClass('js_voice_icon')) {
        let muteElem = $(e.target).hasClass('js_voice_icon') ? e.target : $(e.target).parents('.js_voice_icon')[0];
        let videoElem = $(muteElem).siblings('video')[0];
        let slider = '';
        if ($(this).parents('.swiper-initialized').length > 0 && typeof $(this).parents('.swiper-initialized')[0].swiper != 'undefined') {
            slider = $(this).parents('.swiper-initialized')[0].swiper;
        }
        if (videoElem) {
            if (videoElem.muted) {
                videoElem.muted = false;
                $(muteElem).removeClass('muted')
                if (slider != '') {
                    slider.autoplay.stop();
                }
            } else {
                $(muteElem).addClass('muted')
                videoElem.muted = true;
                if (slider != '') {
                    slider.autoplay.start();
                }
            }
        }
    } else if ($(this).attr('data-href')) {
        let targetType = $(this).attr('data-target');
        if (targetType == '_self') {
            location.href = $(this).attr('data-href');
        } else {
            window.open($(this).attr('data-href'), '_blank').focus();
        }
    }
});

$(document).on("click", ".js_close_ytb_popup", function () {
    $('#js_ytb_video_cont').html('').hide();
});

window.addEventListener('DOMContentLoaded', (event) => {
    toTopBtnCont = document.getElementById('js_to_top_cont');
    webHdr = document.getElementById('header_fix');
    document.removeEventListener('scroll', handleDocumentScroll, false);
    document.addEventListener('scroll', handleDocumentScroll, false);
    if (document.getElementById('js_to_top')) {
        document.getElementById('js_to_top').addEventListener('click', function () {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        });
    }
    handleDocumentScroll();

    if (document.documentElement.dataset.type == 'Mobile') {
        const element = document.querySelector('.js_rg_cont');
        if (element != null) {
            const announcement = document.querySelector('#js_announcements_container:not(.d-none)');
            const body = document.body;
            const initialRect = element.getBoundingClientRect();
            const targetScrollPoint = initialRect.top + window.scrollY - (announcement ? announcement.offsetHeight : 0);
            window.addEventListener('scroll', () => {
                if (window.scrollY >= targetScrollPoint - 1 && !document.getElementById('js_rg_cont_from_header')?.classList.contains('hidden')) {
                    body.classList.add('fixed_reg_btns');
                } else {
                    body.classList.remove('fixed_reg_btns');
                }
            });
            let leftNav = document.querySelector('.js_left_nav_bar');
            leftNav?.addEventListener('scroll', () => {
                leftNav.classList.toggle('left_fixed_reg_btns', leftNav.scrollTop > 0);
            });
        }
    }
});

$(document).on('click', '.js_copy_button', function () {    
    let copyValElem = $(this).siblings('.js_copy_val')[0];
    if (copyValElem == undefined) {
        copyValElem = $(this).closest('div').find('.js_copy_val')[0]
    }   
    let text = '';
    if (copyValElem.tagName == 'INPUT') {
        text = copyValElem.value;
    } else {
        text = copyValElem.innerText;
    }
    let msgTxt = this.dataset.valMsg != undefined ? this.dataset.valMsg : 'Copied';
    if (!copyBtnClicked) {
        copyBtnClicked = true;
        writeToClipboard(text);

        let done = `<div class='copy_msg js_copy_msg_info'> <span class='dynamic_icon'>&#57477</span>${msgTxt}</div>`;
        $('body').append(done);
        if ($(this).hasClass("js_refer")) {
            createToast('success', msgTxt, 4000);
        }

        setTimeout(function () {
            $('.js_copy_msg_info').fadeOut(300, function () {
                $('.js_copy_msg_info').remove();
            });
        }, 1000);
        setTimeout(function () {
            copyBtnClicked = false;
        }, 1500);
    }
});

$(document).on('click', '.js_sidebar_ddwn_btn', function () {
    $(this).parents('.js_sidebar_ddwn').toggleClass('opened');
});

$(document).on('click', '.js_cashier_popup', function (e) {
    let paymentType = $(this).attr('data-paymentType');
    openCashierPopup(paymentType);
});

$(document).on('click', '.js_cashier_close', function (e) {
    closeCashierPopup();
});


$(document).on('click', '#js_deposit_rm', function (e) {
    openBonusRequestPopup();
});

$(document).on('click', '.js_bn_request_popup', function (e) {
    openBonusRequestPopup();
});

$(document).on('click', '.js_newsletter_checkbox', function (e) {
    this.value = this.checked;
});

$(document).on('click', '.js_jackpot_link', function (e) {

    e.preventDefault();
    e.stopPropagation();
    let redirectUrl = $(this).parents('.js_jacpkpots_cont').attr('data-url');
    if (redirectUrl && redirectUrl != '') {
        if (typeof WidgetBasedPageHelper == 'object' && typeof WidgetBasedPageHelper.init === 'function') {
            getPageContent(redirectUrl, false);           
            if (window.js_topJackpot_cover) {
                $('body').removeClass('ofh');
                $('#js_topJackpot_cover').remove();
                $('.top_jackpots__hover_block').css('bottom', '-500px');
            }
        } else {
            if (document.location.href.toLowerCase().includes('/lobby/')) {
                $('#js_to_top_cont').removeAttr('style');
                let group = 'all';
                let prv = 'all';
                let groupPrv = redirectUrl.toLowerCase().split('main');
                let urlSplitted = document.location.href.toLowerCase().split('main');
                if (!document.location.href.toLowerCase().includes(groupPrv[0].toLowerCase())) {
                    document.location.href = redirectUrl;
                    return;
                }
                if (groupPrv.length > 1) {
                    let groupPrvSplited = groupPrv[1].split('/');
                    if (groupPrvSplited.length == 3) {
                        group = groupPrvSplited[1];
                        prv = groupPrvSplited[2];
                    } else if (groupPrvSplited.length == 2) {
                        group = groupPrvSplited[1];
                    }
                }

                let allowClick = true;
                if (urlSplitted.length > 1 && groupPrv.length > 1 && urlSplitted[1] == groupPrv[1]) {
                    allowClick = false;
                }
                let slotGroup = $('[data-url="' + group + '"]');
                let egtcat = $('[data-url="' + prv + '"]');
                if (slotGroup.length > 0 && egtcat.length > 0) {
                    if (allowClick) {
                        $('.js_lobby_groups').removeClass('active');
                        $('.js_lobby_cats').removeClass('active');
                        slotGroup[0].classList.add('active');
                        egtcat[0].classList.add('active');
                        gamesData.Page = 0;
                        imgSortIndex = 0;
                        gamesData.CategoryId = [egtcat[0].dataset.id];
                        gamesData.GroupId = slotGroup[0].dataset.id;
                        gamesData.GroupTypeId = slotGroup[0].dataset.typeId;
                        gamesData.TakeCount = slotGroup[0].dataset.takeCount;
                        GetGames('js_games_lobby');
                        setPageUrl();
                    }

                    let slidePos = Number(slotGroup[0].dataset.pos);
                    Lobbies.slider.slideTo(slidePos > 0 ? slidePos - 1 : 0, 0);
                } else {
                    slotGroup = $('.js_lobby_groups');
                }
                if (window.js_topJackpot_cover) {
                    $('body').removeClass('ofh');
                    $('#js_topJackpot_cover').remove();
                    $('.top_jackpots__hover_block').css('bottom', '-500px');
                }
                $('html, body').animate({
                    scrollTop: $(slotGroup[0]).offset().top - 500
                }, 200);
            } else {
                document.location.href = redirectUrl;
            }
        }
    } else {
        if (window.js_topJackpot_cover) {
            $('body').removeClass('ofh');
            $('#js_topJackpot_cover').remove();
            $('.top_jackpots__hover_block').css('bottom', '-500px');
        }
    }
});

$(document).on('click', '.js_acc_btns', function () {
    let elem = this;
    let panel = elem.nextElementSibling;
    elem.classList.toggle("active");
    elem.parentNode.classList.toggle("active");
    if (panel.style.maxHeight) {
        panel.style.maxHeight = null;
    } else {
        panel.style.maxHeight = panel.scrollHeight + "px";
    }
});

$(document).on('click', '.js_pass_eye_btn', function () {
    let btnFor = this.dataset.btnFor;
    if ($(this).hasClass('opened_pass')) {
        $(this).removeClass('opened_pass');
        $('#' + btnFor).attr('type', 'text');
    } else {
        $('#' + btnFor).attr('type', 'password');
        $(this).addClass('opened_pass');
    }
    if (btnFor == "Country") {
        let profFlag = document.getElementById('js_dy_prof_flag');
        if (profFlag != null) {
            if ($('#' + btnFor).attr('type') == 'password') {
                profFlag.classList.add('hidden');
                $(profFlag).parents('.dyn_form_group').removeClass('dyn_form_group_flag');
            } else {
                profFlag.classList.remove('hidden');
                $(profFlag).parents('.dyn_form_group').addClass('dyn_form_group_flag');
            }
        }
    }

});

$(document).on('click', '.js_logout_confirm', function (e) {
    openLogoutConfPopup();
    if (document.body.classList.contains('cw_mob_root-right_sidebar_opened')) {
        $(this).parent().removeClass('opened');
        closeRightSidebar();
    }
});
$(document).on('click', '.js_close_logout_confirm_popup', function (e) {
    e.preventDefault();
    e.stopPropagation();
    let logout_popup = $('body').find('.js_logout_conf_popup_cont');
    if (logout_popup) {
        $(logout_popup).remove();
        $('body').removeClass('ofh');
    }
});

$(document).on('click', '.js_backto_reg_popup', function (e) {
    e.preventDefault();
    e.stopPropagation();
    let reg_warn_popup = $('body').find('.js_regClose_conf_popup_cont');
    if (reg_warn_popup) {
        $(reg_warn_popup).remove();
    }
    window.allowOpenRegCloseConfirmPopup = true;
});
$(document).on('click', '.js_close_reg_popup_confirm', function (e) {
    e.preventDefault();
    e.stopPropagation();
    if ($('#registerForm .js_tl_head_close').hasClass('login')) {
        $('#registerForm .js_tl_head_close').removeClass('login');
        setTimeout(function () { LoginTrigger(); }, 500);
    }
    let reg_warn_popup = $('body').find('.js_regClose_conf_popup_cont');
    if (reg_warn_popup) {
        $(reg_warn_popup).remove();
    }
    window.allowOpenRegCloseConfirmPopup = false;
    $('.js_tl_head_close').closest(".ui-dialog-content").dialog("close");
    click = 0;
    showpopup = true;
    if (typeof escapeHandler == 'function') {
        window.removeEventListener('keydown');
    }
});

$(document).on('click', '.js_close_restricted_message', function () {
    var url = window.location.href.toLocaleLowerCase();
    if (url.includes('/loginrestricted')) {
        url = url.replace('/loginrestricted', '/');
        window.location.href = url;
    } else if (url.includes('/regrestricted')) {
        url = url.replace('/regrestricted', '/');
        window.location.href = url;
    };

    $('#js_restricted_message_cont').remove();
});

window.addEventListener('message', (event) => {
    if (event.data && typeof event.data.type == 'string') {
        let eventType = event.data.type.toLowerCase();
        if (eventType.startsWith('cw')) {
            switch (eventType) {
                case 'cw_open_declarations':
                    if (hasLoginButton(document)) {
                        LoginTrigger();
                    } else {
                        let lang = document.documentElement.lang;
                        let type = document.documentElement.dataset.type;
                        if (type && type.toLowerCase() == 'mobile') {
                            let url = document.location.href.toLowerCase();
                            if (url.includes('/account/declarations')) {
                                let cashierCloseBtn = document.querySelector('.js_cashier_close');
                                if (cashierCloseBtn != null) {
                                    closeRightSidebar();
                                    closeCashierPopup();
                                }
                            } else {
                                window.location.href = '/' + lang + '/Account/Declarations';
                            }
                        } else {
                            let declarationsPopupBtn = document.querySelector('#declarations_tab');
                            let url = '/' + lang + '/Account/Declarations';
                            if (declarationsPopupBtn != null) {
                                loadTab('declarations_tab', url, function () {
                                    activateTab('declarations_tab');
                                });
                            } else {
                                showAccountPopup(url, 'declarations_tab');
                            }
                        }
                    }
                    break;
                case 'cw_close_cashier':
                    closeCashierPopup();
                    break;
                case 'cw_update_profile':
                    if (!hasLoginButton(document)) {
                        let type = document.documentElement.dataset.type;
                        if (type && type.toLowerCase() == 'mobile') {
                            let url = document.location.href.toLowerCase();
                            if (url.includes('/account/profile')) {
                                closeRightSidebar();
                                let cashierCloseBtn = document.querySelector('.js_cashier_close');
                                if (cashierCloseBtn != null) {
                                    closeCashierPopup();
                                }
                            } else {
                                ProfileTrigger();
                            }
                        } else {
                            let profilePopupBtn = document.querySelector('#profile_tab');
                            if (profilePopupBtn != null) {
                                loadTab('profile_tab', profilePopupBtn.dataset.href, function () {
                                    activateTab('profile_tab');
                                });
                            } else {
                                ProfileTrigger();
                            }
                        }

                    }
                    break;
                default:
                    console.warn(`Wrong command: The "${event.data.type}" does not supported.`)
                    break;
            }
        }
    }
});

const TopProgressBar = (function () {
    let bar = null;
    let progress = 0;
    let frame = null;
    let isRunning = false;
    let activeToken = null;

    const sessions = new Map();

    let config = {
        trickleSpeed: 0.006,
        targetOpacity: 0.3,
    };

    function createBar() {
        if (bar) return;

        bar = document.createElement('div');
        bar.classList.add('cw_progress_bar')
        Object.assign(bar.style, {
            position: 'fixed',
            top: '0',
            left: '0',
            height: '3px',
            width: '100%',
            transform: 'scaleX(0)',
            transformOrigin: 'left',
            backgroundColor: 'var(--btn-primary, var(--cwButtonBg))',
            zIndex: '9999',
            opacity: '1',
            transition: 'transform 0.2s ease-out, opacity 0.3s ease',
            pointerEvents: 'none',
            willChange: 'transform, opacity',
        });
        document.body.appendChild(bar);
    }

    function loop() {
        if (!isRunning) return;

        const delta = Math.random() * config.trickleSpeed;

        if (progress < 0.9) {
            progress = Math.min(progress + delta, 0.9);
            update();
            frame = requestAnimationFrame(loop);
        }
    }

    function update() {
        if (bar) {
            bar.style.transform = `scaleX(${progress})`;
        }
    }

    function start(options = {}) {
        config = {
            ...config,
            ...options,
        };

        createBar();
        progress = 0;
        isRunning = true;
        update();
        frame = requestAnimationFrame(loop);

        const token = Symbol('progress');
        activeToken = token;

        let targetEl = null;

        if (options.target) {
            targetEl = typeof options.target === 'string'
                ? document.querySelector(options.target)
                : options.target;

            if (targetEl) {
                targetEl.style.transition = 'opacity 0.1s ease';
                targetEl.style.opacity = config.targetOpacity;
                targetEl.style.pointerEvents = 'none';
            }
        }
        sessions.set(token, { targetEl });
        return token;
    }

    function done(token) {

        if (!sessions.has(token)) return;

        const { targetEl } = sessions.get(token);
        sessions.delete(token);

        if (token !== activeToken) {
            if (targetEl) {
                targetEl.style.opacity = '1';
                targetEl.style.pointerEvents = '';
            }
            return;
        }

        isRunning = false;
        cancelAnimationFrame(frame);
        progress = 1;
        update();

        if (targetEl) {
            targetEl.style.opacity = '1';
            targetEl.style.pointerEvents = '';
        }

        setTimeout(() => {
            if (bar) bar.style.opacity = '0';

            setTimeout(() => {
                if (bar && bar.parentNode) {
                    bar.parentNode.removeChild(bar);
                    bar = null;
                }
                progress = 0;
                activeToken = null;
            }, 300);
        }, 200);
    }

    return { start, done };
})();

async function getTelemetryData(params, version) {
    
    if (typeof (Worker) === "undefined") {
        window._w_telemetry_promise = null;
        return Promise.reject(new Error("Web Worker API is not supported"));
    }

    if (!window._w_worker) {
        window._w_worker = new Worker('/Scripts/Util/core-telemetry.js?v=1.0.8');
    }

    return new Promise((resolve, reject) => {
        const handleResponse = (e) => {
            window._w_worker.removeEventListener('message', handleResponse);
            if (e.data.success) {
                resolve(e.data);
            } else {
                reject(new Error(e.data.error));
            }
        };
        window._w_worker.addEventListener('message', handleResponse);

        window._w_worker.onerror = (err) => {
            window._w_worker.removeEventListener('message', handleResponse);
            reject(err);
        };

        if (version === 'v') {
            window._w_worker.postMessage({ m: 'v', p: params });
        } else {
            window._w_worker.postMessage({ m: 'v1' });
        }
    });
}
function appendParamInForm(elemName, val, formId) {
    let lg_param = document.getElementById('js_lg_' + elemName);
    if (lg_param != null) {
        lg_param.value = val;
    } else {
        let lgForm = document.getElementById(formId);
        const lg_paramInput = document.createElement('input');
        lg_paramInput.type = 'hidden';
        lg_paramInput.name = elemName;
        lg_paramInput.id = 'js_lg_' + elemName;
        lg_paramInput.value = val;
        lgForm.appendChild(lg_paramInput);
    }
}
function setLgParam(val, formId) {
    if (val.first) {
        appendParamInForm('loginParam', val.first, formId);
    }
    if (val.second) {
        appendParamInForm('loginParam1', val.second, formId);
    }
    appendParamInForm('loginParam2', Date.now(), formId);
}

window.addEventListener('storage', function (event) {
    if (event.key === 'currency_changed' && event.newValue) {
        localStorage.removeItem('currency_changed');
        window.location.reload();
    }
});

function createDormantPopup(msg) {
    return `<div class="toast-container" id="js-dormant-cont">
                            <div class="toast system active">
                                <i class="dynaimc_icon  cw_icon_info_v1 social__pointer-none"></i>
                                <p class="t-title social__pointer-auto">${msg}</p>
                                <button class="t-close"><i class="cw_icon_close_v2 social__pointer-none"></i></button>
                            </div>
                        </div>`;
}

function truncateUrlAtColon(url) {
    if (!url) {
        return '';
    }
    const colonIndex = url.indexOf(':');

    if (colonIndex !== -1) {
        return url.substring(0, colonIndex).trim();
    }
    return url;
}

function showAfterLoginInfoPopup(message) {
    const modalContainer = document.createElement('div');
    modalContainer.innerHTML = `
        <div class="magic-link-modal d-flex justify-content-center align-items-center">
            <div class="magic-link-modal__overlay">
                <div class="magic-link-modal__content">
                    <div class="magic-link-modal__message d-flex align-items-center flex-column align-items-center">
                        <i class="cw_icon_mail"></i>
                        ${message}
                    </div>
                    <div class="magic-link-modal__actions d-flex align-items-center align-items-center">
                        <button type="button" class="magic-link-modal__button bg-primary" automation="confirm_button" id="js_close_info_popup_btn" data-role="none">Ok</button>
                    </div>
                </div>
            </div>
        </div>
    `;
    $('body').addClass('ofh');
    document.body.appendChild(modalContainer);

    const closeButton = modalContainer.querySelector('#js_close_info_popup_btn');
    if (closeButton) {
        closeButton.addEventListener('click', () => {
            $('body').removeClass('ofh');
            modalContainer.remove();
        });
    }
}
function openRegulatoryInfoPopup(placement, btnId) {
    var hasOfhClass = document.body.classList.contains('ofh');
    if (btnId) {
        showHideButtonLoader(btnId, true);
    }
    return $.ajax({
        type: 'POST',
        url: '/responsiblegaming/openregulatoryinfo',
        data: { placement: placement },
        showLoader: false,
        success: function (result, status, xhr) {
            if (btnId) {
                showHideButtonLoader(btnId, false);
            }
            $('body').append(dlAnimate(result));
            if (!hasOfhClass) {
                document.body.dataset.removeOfh = true;
                document.body.classList.add('ofh');
            }
        }
    });
};

function redirectToResponsibleGamingPage() {
    let linkElem = document.querySelector('.js_rg_redirection_btn');
    if (linkElem) {
        linkElem.click();
    }
};

(() => {
    var allowClick = true;
    $(document).on('click', '.js_rg_regulatory_btn', function (e) {
        let placement = $(this).data('placement');
        let btnId = this.id;
        if (allowClick) {
            allowClick = false;
            openRegulatoryInfoPopup(placement, btnId).then(() => { allowClick = true; });
        }
    });
})();