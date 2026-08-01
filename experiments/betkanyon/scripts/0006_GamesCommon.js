var GamesCommon = GamesCommon || (function () {
    return {
        init: function (args) {
            $.extend(this, args);
        }
    }
}());
var gameJack, hvrJackpot, gameJackElem
var getCumulativeJackpotLock = true;
var allowClick = true;
var imgSortIndex = 0;
var gameJackXhttp;
function GetGamesByGroup(append, isSliderItem, gamesByGroupData) {
    $.ajax({
        type: "POST",
        data: gamesByGroupData,
        url: "/DynamicLobbyHelper/GetGamesByGroup",
        success: function (result) {
            let gmsCont = document.getElementById('js_lobby_group_' + result.GroupId);
            let lobbyUrl = gmsCont.dataset.lobbyurl;
            let prwType = GamesCommon.lobbyPreviewType == undefined ? gmsCont.dataset.previewType : GamesCommon.lobbyPreviewType;
            let takeCount = Number(gmsCont.dataset.takeCount);
            let wrap = gmsCont.dataset.wrap;
            gmsCont.dataset.hasNext = result.HasNext;
            if (isSliderItem) {

                if (GamesCommon.gameCardType == 4) {
                    var html = createGameHtmlSpec(result.GamesOutput, '', lobbyUrl, prwType, wrap == 'true' ? takeCount : undefined, true);
                } else {
                    var html = createGamesHtmlV1(result.GamesOutput, '', lobbyUrl, prwType, true);
                }
                document.getElementById('js_mlkd_widget').swiper.appendSlide(html);
            } else {
                let gamesLength = result.GamesOutput.length;
                if (gamesLength > 0) {
                    drawGames('js_lobby_group_' + result.GroupId, result.GamesOutput, append, "", lobbyUrl, prwType, wrap == 'true' ? takeCount : undefined);

                    if (gamesLength <= takeCount) {
                        $(gmsCont).addClass('lca-most-liked-no-slider d-flex');
                    } else {
                        $(gmsCont).parent().find('.js_slider_prev').removeClass('hidden');
                        $(gmsCont).parent().find('.js_slider_next').removeClass('hidden');
                        new Swiper('#js_mlkd_widget', {
                            loop: false,
                            slidesPerView: wrap == 'true' ? 1 : takeCount,
                            slidesPerGroup: wrap == 'true' ? 1 : takeCount,
                            preloadImages: false,
                            autoplay: false,
                            spaceBetween: takeCount == 4 ? 8 : 12,
                            navigation: {
                                nextEl: '.js_slider_next',
                                prevEl: '.js_slider_prev',
                            },
                            on: {
                                transitionEnd: function (swiper) {

                                    if (swiper.isEnd) {
                                        let hasNext = gmsCont.dataset.hasNext;
                                        let page = Number(gmsCont.dataset.page);
                                        if (hasNext == 'true') {
                                            gmsCont.dataset.hasNext = false;
                                            var data = {
                                                GroupId: gmsCont.dataset.id,
                                                GroupTypeId: gmsCont.dataset.typeId,
                                                TakeCount: takeCount,
                                                Page: page + 1,
                                                LobbyUrl: gmsCont.dataset.lobbyurl,
                                                Lang: document.documentElement.lang,
                                                Device: document.documentElement.dataset.type.toLowerCase(),
                                                Currency: GamesCommon.currencyCode
                                            }
                                            gmsCont.dataset.page = data.Page;
                                            GetGamesByGroup(false, true, data);
                                        }

                                    }
                                }
                            }
                        });
                    }
                } else {
                    if (gmsCont && gmsCont.parentNode) {
                        gmsCont.parentNode.classList.add('hidden');
                    }
                }
            }
        }
    });
}

function getLandingWidgetGames(widgetGamesData, removeSlides) {
    $.ajax({
        type: "POST",
        data: widgetGamesData,
        url: "/DynamicLobbyHelper/GetGamesByGroup",
        success: function (result) {
            let curWidgetInfo = widgetGamesData;
            let swElem = document.getElementById('js_lg_ws_' + curWidgetInfo.WidgetId);
            swElem.querySelector('.js_lg_w_names.active').dataset.hasNext = result.HasNext;
            if (typeof swElem.swiper == 'undefined') {
                new Swiper(swElem, {
                    loop: false,
                    slidesPerView: 1,
                    slidesPerGroup: 1,
                    navigation: {
                        nextEl: '#js_lg_w_next_' + curWidgetInfo.WidgetId,
                        prevEl: '#js_lg_w_prev_' + curWidgetInfo.WidgetId,
                    },
                    virtual: {
                        enabled: true,
                        slides: createMinInfoGameCardArr(result.GamesOutput, curWidgetInfo.LobbyUrl, true, curWidgetInfo.TakeCount),
                    },
                    on: {
                        slideChange: function (swiper) {
                            let widgetInfo = swiper.$el[0].querySelector('.js_lg_w_names.active');
                            if (swiper.isEnd) {
                                let hasNext = widgetInfo.dataset.hasNext;
                                let page = Number(widgetInfo.dataset.page);
                                if (hasNext == 'true') {
                                    widgetInfo.dataset.hasNext = false;
                                    let data = {
                                        GroupId: widgetInfo.dataset.id,
                                        WidgetId: widgetInfo.dataset.widgetId,
                                        GroupTypeId: widgetInfo.dataset.typeId,
                                        TakeCount: widgetInfo.dataset.takeCount,
                                        Page: page + 1,
                                        LobbyUrl: widgetInfo.dataset.lobbyurl,
                                        Lang: document.documentElement.lang,
                                        Device: document.documentElement.dataset.type.toLowerCase(),
                                        Currency: GamesCommon.currencyCode
                                    }
                                    widgetInfo.dataset.page = data.Page;
                                    getLandingWidgetGames(data);
                                }
                            }
                        }
                    }
                });
            } else {
                if (removeSlides) {
                    swElem.swiper.virtual.removeAllSlides();
                }
                swElem.swiper.virtual.appendSlide(createMinInfoGameCardArr(result.GamesOutput, curWidgetInfo.LobbyUrl, removeSlides, curWidgetInfo.TakeCount));
            }
        }
    });
}

function createMinInfoGameCardArr(games, lobbyUrl, split, takeCount) {
    let length = games.length;
    const gameSlides = [];
    const difference = takeCount - length;
    if (difference > 0) {
        for (let i = 0; i < difference; i++) {
            games.push({ Id: -1 });
        }
        length = games.length;
        if (split && difference >= length / 2) {
            length = length / 2;
            split = false;
        }
    }

    let html = '';
    for (let i = 0; i < length; i++) {
        html += createMinInfoGameCard(games[i], lobbyUrl);
        if (split && (i + 1) == length / 2) {
            gameSlides.push(html);
            html = '';
        }
    }
    gameSlides.push(html);
    return gameSlides;
}

function createMinInfoGameCard(game, lobbyUrl) {
    if (game.Id == -1) {
        return `<div class="lca-card lca-card--v1"></div>`;
    }
    let html = '';
    let langHtml = '';
    let gameUrl = lobbyUrl != 'undefined' && lobbyUrl != '' ? `${game.URL}-${lobbyUrl}` : game.URL;
    let cdn = game.UseRmCdn ? GamesCommon.RmCdnUrl : GamesCommon.cdnUrl;
    for (var l = 0; l < game.LanguageIds.length; l++) {
        langHtml += `<div class="lca-card-flag ${game.LanguageIds[l].toLowerCase()}"style="background-image: url(${GamesCommon.cdnUrl}Img/sprites/flags_sprite.png)"></div>`;
        if (l == 2) {
            break;
        }
    }
    html = `<div class="lca-card lca-card--v1 js_dl_games_cont" data-game-id="${game.Id}" data-order-id="${game.Order}" ><div class="lca-card-body"><img class="w-100 lca-card-img animated" src="${cdn + game.Image}" alt="${game.Description}" loading="lazy">` +
        `<div class="lb_card_topitems absolute flex_center_between">`;
    if (game.Badges)
    {
        html += game.Badges;
    }
    html+= `<div class="lca-card-flag-wrapper animate">${langHtml}</div>
            </div>
            </div>`;
    if (game.ContributionPercent != undefined && game.ContributionPercent != null) {
        html += `<div class="contribution_icon"><i class="dynamic_icon"></i><p>${game.ContributionPercent}%</p></div>`;
    }

    if ((game.MinMaxLimits[0] != '0' && game.MinMaxLimits[1] != '0') || game.MinMaxLimits[2] != '0') {
        html += `<div class="lca-card-footer d-flex">`;
        if (game.MinMaxLimits[2] > '0') {
            html += `<div class="lca-card-maxwin-wrapper animate">${game.MinMaxLimits[2]}</div>`;
        }
        if (game.MinMaxLimits[0] != '0' && game.MinMaxLimits[1] != '0') {
            html += `<div class="lca-card-price text-right mwAuto"><div class="d-flex gx-1 align-items-center justify-content-end"><span class="lca-limit-count no-rtl-needed">${game.MinMaxLimits[0]}-${game.MinMaxLimits[1]}</span> ${GamesCommon.currencyCode} </div></div>`;
        }
        html += `</div>`;
    }
    html += `<div class="lca-card-hover animate"><div class="lca-card-hover-header"><div class="lca-card-name">${game.Description}</div></div>` +
        `<div class="lca-card-btn-wrapper d-flex align-items-center justify-content-center"><a class="h-bg-primary game__link_real js_dl_play"`;
    
    if (GamesCommon.userId > 0) {
        html += `href="/${GamesCommon.language}/play/real/${gameUrl}"><span class="dynamic_icon">&#58160</span><span class="lca-card-play-text">${GamesCommon.trns.Play}</span></a>`;
    } else {
        html += `data-href="/${GamesCommon.language}/play/real/${gameUrl}"><span class="dynamic_icon">&#58160</span><span class="lca-card-play-text">${GamesCommon.trns.Play}</span></a>`;
    }

    if (game.HasDemo) {
        html += `<a class="h-bg-secondary game__link_demo js_dl_play_demo" href="/${GamesCommon.language}/play/fun/${gameUrl}">${GamesCommon.trns.Demo}</a>`;
    }
    html += `</div></div></div>`;
    return html;
}

function createGameHtml(games, gridType, lobbyUrl, prwType, gridWrapCount, isSlider) {
    var html = '';
    for (var i = 0; i < games.length; i++) {
        var favClass = '';
        var likeClass = '';
        var langHtml = '';
        var gridClass = isSlider ? 'swiper-slide ' : '';
        var imgType = '';
        var imgUrl = games[i].Image;
        let cdn = games[i].UseRmCdn ? GamesCommon.RmCdnUrl : GamesCommon.cdnUrl;
        if (gridWrapCount != undefined && (i == 0 || i % gridWrapCount == 0)) {
            html += '<div class="grid_inner">'
        }
        if (games[i].IsFavorite) {
            favClass = 'active';
        }
        if (games[i].IsLiked) {
            likeClass = 'active';
        }
        for (var l = 0; l < games[i].LanguageIds.length; l++) {
            langHtml += '<div class="lca-card-flag ' + games[i].LanguageIds[l].toLowerCase() + '"style="background-image: url(' + GamesCommon.cdnUrl + 'Img/sprites/flags_sprite.png)"></div>';
        }
        if (gridType == 2 || gridType == 4) {
            imgSortIndex++;
            imgType = getImgType(gridType);
            if (imgType == 'horizontal') {
                gridClass += 'lca-card-w2';
                imgUrl = games[i].HorizontalImage;
            } else if (imgType == 'vertical') {
                gridClass += 'lca-card-h2';
                imgUrl = games[i].VerticalImage;
            }
        }
        if (games[i].HasJackpot) {
            html += '<div class="lca-card js_dl_games_cont ' + gridClass + '" data-game-id ="' + games[i].Id + '" onmouseenter="startAction(this);"  onmouseleave="stopAction();"><div class="lca-card-body">';
        } else {
            html += '<div class="lca-card js_dl_games_cont ' + gridClass + '" data-game-id ="' + games[i].Id + '"><div class="lca-card-body">';
        }
        html += '<img class="w-100 lca-card-img animated" src="' + cdn + imgUrl + '" alt="' + games[i].Description + '" loading="lazy">' +
            '<div class="lca-card-flag-wrapper animate">' + langHtml + '</div>' +
            '<div class="lca-card-badge-wrapper animate">' + games[i].Badges + '</div>';

        if (games[i].MinMaxLimits[2] > '0') {
            html += '<div class="lca-card-maxwin-wrapper animate text-primary">' + games[i].MinMaxLimits[2] + '</div></div>';
        } else {
            html += '</div>';
        }
        if (prwType != '2') {
            html += '<div class="lca-card-footer d-flex"><div class="lca-card-name flex-grow-1 no-rtl-needed">' + games[i].Description + '</div>';
            if (games[i].MinMaxLimits[0] == '0' && games[i].MinMaxLimits[1] == '0') {
                html += '<div class="lca-card-price text-right"><div><span class="lca-limit-count no-rtl-needed"></span><span class="currency_icon"></span></div></div></div>';
            } else {
                html += '<div class="lca-card-price text-right"><div><span class="lca-limit-count no-rtl-needed">' + games[i].MinMaxLimits[0] + ' - ' + games[i].MinMaxLimits[1] + '</span> '  + GamesCommon.currencyCode + ' </div></div></div>';
            }
        }
        html += '<div class="lca-card-hover animate"><div class="lca-card-hover-header">' +
            '<div class="lca-card-name">' + games[i].Description + '</div><span class="star_icon js_game_fav ' + favClass + '"></span></div>' +
            '<div class="lca-card-btn-wrapper d-flex align-items-center justify-content-center flexCol">' +
            '<a class="h-bg-primary game__link_real js_dl_play"';

        if (GamesCommon.userId > 0) {
            html += 'href = "/' + GamesCommon.language + '/play/real/' + games[i].URL + '-' + lobbyUrl + '" > ' + GamesCommon.trns.Play + '</a > ';
        } else {
            html += 'data-href = "/' + GamesCommon.language + '/play/real/' + games[i].URL + '-' + lobbyUrl + '" > ' + GamesCommon.trns.Play + '</a > ';
        }
       
         if (games[i].HasDemo) {
            html += '<a class="h-bg-secondary game__link_demo js_dl_play_demo" href="/' + GamesCommon.language + '/play/fun/' + games[i].URL + '-' + lobbyUrl + '">' + GamesCommon.trns.Demo + '</a>';
        }

        if (prwType == '2') {
            if (games[i].MinMaxLimits[0] == '0' && games[i].MinMaxLimits[1] == '0') {
                html += '<div class="lca-card-price text-right"><span></span><span class="currency_icon"></span></div></div>';
            } else {
                html += '<div class="lca-card-price text-right"><span>' + games[i].MinMaxLimits[0] + ' - ' + games[i].MinMaxLimits[1] + '</span> ' + GamesCommon.currencyCode + ' </div></div>';
            }
            html += '<div class="lca-card-hover-footer preview-footer-' + prwType + ' d-flex"><div class="jackpot__value flex alCen text-primary">';
        } else {
            html += '</div><div class="lca-card-hover-footer d-flex"><div class="jackpot__value flex alCen text-primary">';
        }

        if (games[i].HasJackpot) {
            html += '<span class="diamond_icon"></span><span class="js_game_jackpot"></span>';
        }
        html += '</div><div class="lca-card-likes preview-likes-' + prwType + ' d-flex align-items-center js_game_like"><span class="like_icon js_game_like_icon ' + likeClass + '"></span><span class="js_game_likes_count">' + games[i].LikesCount + '</span></div></div></div></div>';
        if (gridWrapCount != undefined && ((i + 1) % gridWrapCount == 0 || (games.length < gridWrapCount && (i + 1) == games.length))) {
            html += '</div>'
        }
    }
    return html;
}

function createGameHtmlSpec(games, gridType, lobbyUrl, prwType, gridWrapCount, isSlider) {
    var html = '';
    for (var i = 0; i < games.length; i++) {
        var favClass = '';
        var likeClass = '';
        var langHtml = '';
        var gridClass = isSlider ? 'swiper-slide ' : '';
        var imgType = '';
        var imgUrl = games[i].Image;
        let cdn = games[i].UseRmCdn ? GamesCommon.RmCdnUrl : GamesCommon.cdnUrl;
        if (gridWrapCount != undefined && (i == 0 || i % gridWrapCount == 0)) {
            html += '<div class="grid_inner">'
        }
        if (games[i].IsFavorite) {
            favClass = 'active';
        }
        if (games[i].IsLiked) {
            likeClass = 'active';
        }
        for (var l = 0; l < games[i].LanguageIds.length; l++) {
            langHtml += '<div class="lca-card-flag ' + games[i].LanguageIds[l].toLowerCase() + '"style="background-image: url(' + GamesCommon.cdnUrl + 'Img/sprites/flags_sprite.png)"></div>';
        }
        if (gridType == 2 || gridType == 4) {
            imgSortIndex++;
            imgType = getImgType(gridType);
            if (imgType == 'horizontal') {
                gridClass += 'lca-card-w2';
                imgUrl = games[i].HorizontalImage;
            } else if (imgType == 'vertical') {
                gridClass += 'lca-card-h2';
                imgUrl = games[i].VerticalImage;
            }
        }
        if (games[i].HasJackpot) {
            html += '<div class="lca-card js_dl_games_cont ' + gridClass + '" data-game-id ="' + games[i].Id + '" onmouseenter="startAction(this);"  onmouseleave="stopAction();"><div class="lca-card-body">';
        } else {
            html += '<div class="lca-card js_dl_games_cont ' + gridClass + '" data-game-id ="' + games[i].Id + '"><div class="lca-card-body">';
        }
        html += '<img class="w-100 lca-card-img animated" src="' + cdn + imgUrl + '" alt="' + games[i].Description + '" loading="lazy">' +
            '<div class="lca-card-flag-wrapper animate">' + langHtml + '</div>' +
            '<div class="lca-card-badge-wrapper animate">' + games[i].Badges + '</div>';

        if (prwType != '2') {
            html += '<div class="lca-card-footer d-flex"><div class="lca-card-name flex-grow-1 no-rtl-needed">' + games[i].Description;
            html += '<div class="lca-card-cat flex-grow-1 no-rtl-needed">' + games[i].CatName + '</div></div>';
            if (games[i].MinMaxLimits[0] == '0' && games[i].MinMaxLimits[1] == '0') {
                html += '<div class="lca-card-price text-right"><div><span class="lca-limit-count no-rtl-needed"></span></div></div>';
                if (games[i].MinMaxLimits[2] > '0') {
                    html += '<div class="lca-card-maxwin-wrapper animate text-primary">' + games[i].MinMaxLimits[2] + '</div></div>';
                } else {
                    html += '</div>';
                }
            } else {
                html += '<div class="lca-limit-info"><div class="lca-card-price text-right"><div><span class="lca-limit-count no-rtl-needed">' + games[i].MinMaxLimits[0] + ' - ' + games[i].MinMaxLimits[1] + '</span> ' + GamesCommon.currencyCode + ' </div></div>';
                if (games[i].MinMaxLimits[2] > '0') {
                    html += '<div class="lca-card-maxwin-wrapper animate text-primary">' + games[i].MinMaxLimits[2] + '</div></div></div>';
                } else {
                    html += '</div></div>';
                }
            }
        }
        html += '<div class="lca-card-hover animate"><div class="lca-card-hover-header">';
        if (games[i].HasJackpot) {
            html += '<span class="diamond_icon"></span><span class="js_game_jackpot"></span>';
        }

        html += '<div class="lca-card-likes preview-likes-' + prwType + ' d-flex align-items-center js_game_like"><span class="like_icon js_game_like_icon ' + likeClass + '"></span><span class="js_game_likes_count">' + games[i].LikesCount + '</span></div><span class="star_icon js_game_fav ' + favClass + '"></span></div>' +
            '<div class="lca-card-info lca-card-container">';
        if (games[i].MinMaxLimits[0] > 0 && games[i].MinMaxLimits[1] > 0) {
            html += '<div class="lca-card-price text-right"><span class="lca-limit-count no-rtl-needed">' + games[i].MinMaxLimits[0] + ' - ' + games[i].MinMaxLimits[1] + ' </span> ' + GamesCommon.currencyCode + ' </div>';
        }

        html += '<div class="lca-card-name">' + games[i].Description + '</div>' +
            '<div class="lca-card-name lca-card-cat">' + games[i].CatName + '</div>' +
            '<div class="lca-card-provider"></div></div>' +
            '<div class="lca-card-btn-wrapper lca-card-container d-flex align-items-center justify-content-start">' +
            '<a class="h-bg-primary game__link_real js_dl_play"';
        if (GamesCommon.userId > 0) {
            html += 'href = "/' + GamesCommon.language + '/play/real/' + games[i].URL + '-' + lobbyUrl + '" > ' + GamesCommon.trns.Play + '</a > ';
        } else {
            html += 'data-href = "/' + GamesCommon.language + '/play/real/' + games[i].URL + '-' + lobbyUrl + '" > ' + GamesCommon.trns.Play + '</a > ';
        }
        if (games[i].HasDemo) {
            html += '<a class="h-bg-secondary game__link_demo js_dl_play_demo" href="/' + GamesCommon.language + '/play/fun/' + games[i].URL + '-' + lobbyUrl + '">' + GamesCommon.trns.Demo + '</a>';
        }
        html += '</div></div></div></div>';
        if (gridWrapCount != undefined && ((i + 1) % gridWrapCount == 0 || (games.length < gridWrapCount && (i + 1) == games.length))) {
            html += '</div>'
        }
    }
    return html;
}

function drawGames(contId, games, append, gridType, lobbyUrl, prwType, gridWrapCount) {
    var html = '';
    let isForSlider = $('#' + contId).hasClass('swiper-wrapper');
    if (games.length > 0) {
        if (GamesCommon.gameCardType == 4) {
            html += createGameHtmlSpec(games, gridType, lobbyUrl, prwType, gridWrapCount, isForSlider);
        } else {
            html += createGamesHtmlV1(games, gridType, lobbyUrl, prwType, isForSlider);
        }
    } else {
        if (gamesData.SearchText != '') {
            html += '<div class="lca-filter-no-result text-center lobbyFilter_empty"><span class="search__icon"></span><p>' + GamesCommon.trns.NoSearchResults + ' "' + gamesData.SearchText + '"</p></div>';
        } else if (gamesData.GroupTypeId == GamesCommon.favoriteGroupType) {
            html += '<div class="casino_nav_fav_game_not_found lobbyFilter_empty"><img src="' + GamesCommon.cdnUrl + 'Img/icons/redesign/favorite_big_star.svg"/><p>' + GamesCommon.trns.YouHaveNoFavoriteGames + '</p><span>' + GamesCommon.trns.ToAddFavGames + '</span></div>';
        } else if (gamesData.GroupTypeId == GamesCommon.lastPlayedGroupType) {
            html += '<div class="casino_nav_fav_game_not_found lobbyFilter_empty"><p class="last-played-icon dynamic_icon">&#57944</p><span>' + GamesCommon.trns.YouHaveNoLastPlayedGames + '</span></div>';
        } else {
            html += '<div class="lca-no-game lobbyFilter_empty"><span class="ic_no-game"></span><p>' + GamesCommon.trns.NoSuchGameFound + '</p></div>';
        }
    }
    if (append) {
        $('#' + contId).append(dlAnimate(html));
    } else {
        $('#' + contId).html(dlAnimate(html));
    }
}

function createGamesHtmlV1(games, gridType, lobbyUrl, prwType, isSlider) {
    let html = '';
    let imgType = '';
    const length = games.length;

    for (let i = 0; i < length; i++) {
        let imgUrl = games[i].Image;
        let cdn = games[i].UseRmCdn ? GamesCommon.RmCdnUrl : GamesCommon.cdnUrl;
        let favClass = games[i].IsFavorite ? 'active' : '';
        let likeClass = games[i].IsLiked ? 'active' : '';
        let gridClass = isSlider ? 'swiper-slide ' : '';
        let badgesData = games[i].Badges;

        if (gridType == 2 || gridType == 4) {
            imgSortIndex++;
            imgType = getImgType(gridType);
            if (imgType == 'horizontal') {
                gridClass += 'lb_card_h';
                imgUrl = games[i].HorizontalImage;
            } else if (imgType == 'vertical') {
                gridClass += 'lb_card_v';
                imgUrl = games[i].VerticalImage;
            }
        }


        //badgesData = `
        //<div class="lb_card_badge_wrapper lb_card_badge_anim" style="--cwStatusAnimationCount:5;">
        //    <div class="lb_card_badge_inner_wrapper_global">
        //        <div class="lb_card_badge badge_type_exclusive"><i></i><span>text 1</span></div>
        //        <div class="lb_card_badge badge_type_new"><i></i><span>text 222222</span></div>
        //        <div class="lb_card_badge badge_type_exclusive"><i></i><span>text 12454541</span></div>
        //        <div class="lb_card_badge badge_type_soon"><i></i><span>soon</span></div>
        //        <div class="lb_card_badge badge_type_new"><i></i><span>new</span></div>
        //    </div>
        //</div>
        //`;

        html += `<div class="lb_card relative ${gridClass} js_dl_games_cont" data-order-id="${games[i].Order}" data-game-id="${games[i].Id}" ${games[i].HasJackpot ? `onmouseenter="startAction(this);"  onmouseleave="stopAction();"` : ``}><div class="lb_card_body"><img class="lb_card_img" src="${cdn + imgUrl}" alt="${games[i].Description}" ${isSlider ? `` : `loading="lazy"`} /></div>` +
            `<div class="lb_card_topitems absolute flex_center_between"> ${badgesData} ${createMaxWin(games[i])} ${createLanguages(games[i])}</div>`;

        if (prwType != '2') {
            html += createCardFooter(games[i]);
        }
        html += `<div class="lb_card_hover absolute flex_center_between"><div class="lb_card_hover_top flex_center_between w-100">` +
            `<span class="lb_card_like d-flex ${likeClass} js_game_like"><span class="js_game_likes_count">${games[i].LikesCount}</span></span><span class="lb_card_favorite d-flex ${favClass} js_game_fav"></span></div><div class="lb_card_buttons d-flex">`;
        if (games[i].HasDemo) {
            html += `<a class="lb_card_button demo_btn js_dl_play_demo" href="/${GamesCommon.language}/play/fun/${games[i].URL}-${lobbyUrl}">${GamesCommon.trns.Demo}</a>`;
        }
        if (GamesCommon.userId > 0) {
            html += `<a class="lb_card_button play_btn js_dl_play" href="/${GamesCommon.language}/play/real/${games[i].URL}-${lobbyUrl}"><i class="dynamic_icon play_icon">&#58160</i>${GamesCommon.trns.Play}</a>`;
        } else {
            html += `<a class="lb_card_button play_btn js_dl_play" data-href="/${GamesCommon.language}/play/real/${games[i].URL}-${lobbyUrl}"><i class="dynamic_icon play_icon">&#58160</i>${GamesCommon.trns.Play}</a>`;
        }
        html += `</div><div class="lb_card_hover_bottom flex_center_between w-100">`;

        if (games[i].HasJackpot) {
            html += `<div class="lb_card_jackpot_value d-flex align-items-center"><i class="dynamic_icon">&#58451</i><div class="js_game_jackpot component_jackpot_slider no-rtl-needed"></div>` +
                ` ${GamesCommon.currencyCode}</div>`;
        }
        if (prwType == '2' && games[i].MinMaxLimits[0] != '0' && games[i].MinMaxLimits[1] != '0') {
            html += `<div class="lb_card_price"><span class="lb_card_limit_count no-rtl-needed">${games[i].MinMaxLimits[0]} - ${games[i].MinMaxLimits[1]}</span>  ${GamesCommon.currencyCode} </div>`;
        }
        html += `</div></div></div>`;
    }
    return html;
}

function createRecommendedGamesHtml(games) {
    let html = '';
    const length = games.length;

    for (let i = 0; i < length; i++) {
        let imgUrl = games[i].Image;
        let cdn = games[i].UseRmCdn ? GamesCommon.RmCdnUrl : GamesCommon.cdnUrl;
        let favClass = games[i].IsFavorite ? 'active' : '';
        let likeClass = games[i].IsLiked ? 'active' : '';

        html += `<div class="lb_card relative js_dl_games_cont swiper-slide"  data-game-id="${games[i].Id}" ${games[i].HasJackpot ? `onmouseenter="startAction(this);"  onmouseleave="stopAction();"` : ``}><div class="lb_card_body"><img class="lb_card_img" src="${cdn + imgUrl}" alt="${games[i].Description}" loading="lazy" /></div>` +
            `<div class="lb_card_topitems absolute flex_center_between"></div>`;
        if (GamesCommon.lobbyPreviewType != '2') {
            html += `<div class="lb_card_footer flex_center_between"> <p class="lb_card_name">${games[i].Description}</p></div>`;
        }
        html += `<div class="lb_card_hover absolute flex_center_between"><div class="lb_card_hover_top flex_center_between w-100">` +
            `<span class="lb_card_like d-flex ${likeClass} js_game_like"><span class="js_game_likes_count">${games[i].LikesCount}</span></span><span class="lb_card_favorite d-flex ${favClass} js_game_fav"></span></div><div class="lb_card_buttons d-flex">`;
        if (games[i].HasDemo) {
            html += `<a class="lb_card_button demo_btn js_dl_play_demo" href="/${GamesCommon.language}/play/fun/${games[i].URL}">${GamesCommon.trns.Demo}</a>`;
        }
        if (GamesCommon.userId > 0) {
            html += `<a class="lb_card_button play_btn js_dl_play" href="/${GamesCommon.language}/play/real/${games[i].URL}"><i class="dynamic_icon play_icon">&#58160</i>${GamesCommon.trns.Play}</a>`;
        } else {
            html += `<a class="lb_card_button play_btn js_dl_play" data-href="/${GamesCommon.language}/play/real/${games[i].URL}"><i class="dynamic_icon play_icon">&#58160</i>${GamesCommon.trns.Play}</a>`;
        }
        html += `</div><div class="lb_card_hover_bottom flex_center_between w-100">`;

        if (games[i].HasJackpot) {
            html += `<div class="lb_card_jackpot_value d-flex align-items-center"><i class="dynamic_icon">&#58451</i><div class="js_game_jackpot component_jackpot_slider no-rtl-needed"></div>` +
                `  ${GamesCommon.currencyCode} </div>`;
        }
        html += `</div></div></div>`;
    }
    return html;
}

function getImgType(gridType) {
    return gridType == 2 ? gridArrangeWithMosaic1() : gridArrangeWithMosaic2();
}
function gridArrangeWithMosaic1() {
    if (allGamesCount >= 25) {
        if (imgSortIndex == 1 || imgSortIndex == 5 || imgSortIndex == 17) {
            return 'vertical';
        } else if (imgSortIndex == 13 || imgSortIndex == 25) {
            if (imgSortIndex == 25) {
                imgSortIndex = 0;
            }
            return 'horizontal';
        }
    } else if (allGamesCount >= 15) {
        if (imgSortIndex == 1 || imgSortIndex == 5) {
            return 'vertical';
        } else if (imgSortIndex == 13) {
            return 'horizontal';
        }
    } else if (allGamesCount >= 10) {
        if (imgSortIndex == 1 || imgSortIndex == 5) {
            return 'vertical';
        }
    }
    return '';
}
function gridArrangeWithMosaic2() {
    if (allGamesCount >= 14) {
        if (imgSortIndex == 6 || imgSortIndex == 20) {
            return 'vertical';
        } else if (imgSortIndex == 1 || imgSortIndex == 15 || imgSortIndex == 23) {
            return 'horizontal';
        }
        if (imgSortIndex == 30) {
            imgSortIndex = 0;
        }
    }
    return '';
}
function startAction(elem) {
    gameJackElem = elem;
    if (getCumulativeJackpotLock) {
        getCumulativeJackpotLock = false;
        getData('/Common/GetCumulativeJackpot', startAnim);

        hvrJackpot = setInterval(() => {
            getData('/Common/GetCumulativeJackpot', updateAnim)
        }, 30050);
    }
};

function getData(url, cFunction) {
    gameJackXhttp = new XMLHttpRequest();
    gameJackXhttp.onreadystatechange = function () {
        if (this.readyState == 4 && this.status == 200) {
            try {
                var json = JSON.parse(this.responseText);
                cFunction(json);
            } catch (e) {
                console.error("Invalid JSON format");
            }
        }
    };
    gameJackXhttp.open("POST", url, true);
    gameJackXhttp.send();
}

function startAnim(json) {
    if (gameJack instanceof FlipJackpotNumbers) {
        gameJack.destroy();
    }
    gameJack = new FlipJackpotNumbers({
        node: gameJackElem.querySelector('.js_game_jackpot'),
        from: json.OldSumJackPot,
        seperateOnly: json.DigitsAfterpoint,
    });
    gameJack.flipTo({
        to: json.NewSumJackPot,
        direct: false
    });
}

function updateAnim(json, jackpotObject) {
    if (jackpotObject instanceof FlipJackpotNumbers) {
        if (json.OldSumJackPot > json.NewSumJackPot) {
            gameJack.destroy();
            gameJack = new FlipJackpotNumbers({
                node: jackpotObject.node,
                from: json.NewSumJackPot,
                seperateOnly: json.DigitsAfterpoint,
            });
            gameJack.flipTo({
                to: json.OldSumJackPot,
                direct: false
            });
        } else {
            jackpotObject.flipTo({
                to: json.NewSumJackPot,
                direct: false
            });
        }
    }
}

function stopAction() {
    if (gameJack instanceof FlipJackpotNumbers) {
        gameJack.destroy();
    }
    clearInterval(hvrJackpot);
    gameJackXhttp.abort();
    getCumulativeJackpotLock = true;
}

function CreateBadges(badgeTypeId) {
    let badges = '';

    for (var b = 0; b < badgeTypeId.length; b++) {
        switch (badgeTypeId[b]) {
            case 1:
                badges += '<div class="lca-card-badge type-1">Top</div>';
                break;
            case 2:
                badges += '<div class="lca-card-badge type-2">HOT</div>';
                break;
            case 3:
                badges += '<div class="lca-card-badge type-3">JackPot</div>';
                break;
            case 4:
                badges += '<div class="lca-card-badge type-4">New</div>';
                break;
            case 5:
                badges += '<div class="lca-card-badge type-5">Soon</div>';
                break;
            case 6:
                badges += '<div class="lca-card-badge type-6">Premium</div>';
                break;
        }
    }
    return badges;
}

function openLogin(gameUrl = '') {
    if (GamesCommon.hasStaticLoginPage) {
        if (gameUrl != null && gameUrl != '') {
            document.location.href = '/Login/Login?gameUrl=' + gameUrl;
        } else {
            document.location.href = '/Login/Login';
        }
    } else {
        var url = '/Login/Login?gameUrl=' + gameUrl;
        showPopup(url, 'loginContent', {
            position: null,
            dialogClass: 'tl_popup_dialog js_popup_dialog flex_popup_content',
            responsive: false,
        });
    }
}


$(document).on('click', '.js_game_fav', function (e) {
    e.stopPropagation();
    if (GamesCommon.userId == 0) {
        openLogin();
        return;
    }
    if (allowClick) {
        allowClick = false;
        var gameId = $(this).parents('.js_dl_games_cont').attr('data-game-id');

        if ($(this).hasClass('active')) {
            $.ajax({
                url: "/DynamicLobbyHelper/DeleteFromFavList",
                type: "POST",
                data: { gameId: gameId },
                datatype: "json",
                success: function (result) {
                    if (result.Code > 0) {
                        createToast('error', result.Message);
                    } else {
                        $('div[data-game-id="' + gameId + '"] .js_game_fav').removeClass('active');
                    }
                    allowClick = true;
                }
            });
        } else {
            $.ajax({
                url: "/DynamicLobbyHelper/AddToFavList",
                type: "POST",
                data: { gameId: gameId },
                datatype: "json",
                success: function (result) {
                    if (result.Code > 0) {
                        createToast('error', result.Message);
                    } else {
                        $('div[data-game-id="' + gameId + '"] .js_game_fav').addClass('active');
                    }
                    allowClick = true;
                }
            });
        }
    }
});

$(document).on('click', '.js_game_like', function (e) {

    e.stopPropagation();

    if (GamesCommon.userId == 0) {
        openLogin();
        return;
    }
    if (allowClick) {
        allowClick = false;
        var likeIcon = GamesCommon.gameCardType == 4 && typeof WidgetBasedPageHelper == 'undefined' ? $(this).children('.js_game_like_icon') : $(this);
        var gameId = $(this).parents('.js_dl_games_cont').attr('data-game-id');

        if ($(likeIcon).hasClass('active')) {
            $.ajax({
                url: "/DynamicLobbyHelper/RemoveLike",
                type: "POST",
                data: { gameId: gameId },
                datatype: "json",
                success: function (result) {
                    if (result.Code > 0) {
                        createToast('error', result.Message);
                    } else {
                        var likesCount = 0;
                        if (GamesCommon.gameCardType == 4 && typeof WidgetBasedPageHelper == 'undefined') {
                            likesCount = $(likeIcon).siblings('.js_game_likes_count').text();
                            $('div[data-game-id="' + gameId + '"] .js_game_like_icon').removeClass('active');
                        } else {
                            likesCount = $(likeIcon).children('.js_game_likes_count').text();
                            $('div[data-game-id="' + gameId + '"] .js_game_like').removeClass('active');
                        }
                        $('div[data-game-id="' + gameId + '"] .js_game_likes_count').html(Number(likesCount) - 1);

                    }
                    allowClick = true;
                }
            });
        } else {
            $.ajax({
                url: "/DynamicLobbyHelper/AddLike",
                type: "POST",
                data: { gameId: gameId },
                datatype: "json",
                success: function (result) {
                    if (result.Code > 0) {
                        createToast('error', result.Message);
                    } else {
                        var likesCount = 0;
                        if (GamesCommon.gameCardType == 4 && typeof WidgetBasedPageHelper == 'undefined') {
                            likesCount = $(likeIcon).siblings('.js_game_likes_count').text();
                            $('div[data-game-id="' + gameId + '"] .js_game_like_icon').addClass('active');
                        } else {
                            likesCount = $(likeIcon).children('.js_game_likes_count').text();
                            $('div[data-game-id="' + gameId + '"] .js_game_like').addClass('active');
                        }
                        $('div[data-game-id="' + gameId + '"] .js_game_likes_count').html(Number(likesCount) + 1);
                    }
                    allowClick = true;
                }
            });
        }
    }
});

$(document).on('click', '.js_dl_play', function (e) {
    e.preventDefault();
    if (GamesCommon.userId > 0) {
        let gameUrl = $(this).attr('href');
        if (typeof CheckClientVerificationInfo === 'function' && (GamesCommon.isMobileVerified.toLowerCase() == 'false' || GamesCommon.isDocumentVerified.toLowerCase() == 'false')) {
            CheckClientVerificationInfo();
        } else if (typeof insFoundsCheck === 'function') {
            if (insFoundsCheck(e)) {
                document.location.href = gameUrl;
            }
        } else {
            document.location.href = gameUrl;
        }
    } else {
        let gameUrl = $(this).attr('data-href');
        openLogin(gameUrl);
    }
});

$(document).on('click', '.js_dl_play_demo', function (e) {
    e.preventDefault();
    var gameUrl = $(this).attr('href');
    document.location.href = gameUrl;
});
