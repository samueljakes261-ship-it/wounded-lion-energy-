/*Custom Select Menu Start */

$.fn.extend({
    customSelect: function (options) {
 

        // set defaults
        var defaults = {
            hiddenClass: 'tl_sel_custom_popup_reg_hidden',
            wrapperClass: 'tl_sel_custom_popup_reg',
            selectedClass: 'tl_sel_custom_popup_reg_selected',
            optionClass: 'tl_sel_custom_popup_reg_options',
            activeClass: 'active',
            title: 0
        };

        var init = function (options, elem, refresh) {

            refresh = refresh || false;

            elem.each(function () {

                var $this = $(this),
                    numberOfOptions = $(this).children('option').length;

                // setting options and data options
                var opps = $(this).data();

                // merging defaults and options
                var settings = $.extend(
                    $.extend({}, defaults),
                    opps
                );

                var selecedOpt = $(this).children("option:selected");
                var selecedIsoCode = '';
                if (selecedOpt.attr('data-isoCode')) {
                    selecedIsoCode = selecedOpt.attr('data-isoCode')
                }

                if (!refresh) {
                    $this.addClass(settings.hiddenClass);
                    $this.wrap('<div class="' + settings.wrapperClass + '"></div>');
                    $this.after('<div class="' + settings.selectedClass + ' ' + selecedIsoCode + '" id ="custom_' + $(this).attr('id') + '" ></div>');
                } else {
                    $this.next('div.' + settings.selectedClass).off('click');
                    $this.siblings('ul.' + settings.optionClass).remove();
                }
                
                var $styledSelect = $this.next('div.' + settings.selectedClass);
                $styledSelect.text($this.children('option:selected').eq(0).text());

                
                var $list = $('<ul />', {
                    'data-id': $(this).attr('id'),
                    'class': settings.optionClass + ' ' + ($(this).attr('customclass') ? $(this).attr('customclass') : '') + ' ' +  ' ' + $(this).attr('id')
                }).insertAfter($styledSelect);
                var opt1 = $this.children('option');
                var opt = '';
                var isoCode = '';
                for (var i = 0; i < numberOfOptions; i++) {

                    opt = $(opt1[i]);
                    if (opt.attr('data-isoCode') != 'undefined') {
                        isoCode = opt.attr('data-isoCode');
                    }
                    var optAttrs = {
                        text: opt.text(),
                        rel: opt.val(),
                        class: '',
                        isoCode: isoCode
                    };

                    if (settings.title) {
                        optAttrs.title = opt.text();
                    }

                    if (opt.is(':selected')) {
                        optAttrs.class = "active";
                    }

                    if (opt.attr('data-isoCode')) {
                        optAttrs.class += ' ' + opt.attr('data-isoCode');
                    }

                    var $listItem = $('<li />', optAttrs);
                    
                    if (opt.css('display') == 'none') {
                        $listItem.addClass('hidden');
                    }
                    
                    $listItem.appendTo($list);
                }

                if (settings.disabled) {
                    $('#custom_' + $(this).attr('id')).addClass('disabled');
                }
                
            });
        };


        $('body').off('click dblclick', '.' + defaults.optionClass + ' li, .' + defaults.selectedClass);
        $('body').off('click');

        $('body').on('click', '.' + defaults.selectedClass + ':not(.disabled)', function (e) {
            e.stopPropagation();
            if ($(this).hasClass('active')) {
                return;
            }
            var $list = $(this).next('ul.' + defaults.optionClass);

            $(this).attr('data-click-state', 0);

            // showing list options
            $list.find('li').show();

            $('div.' + defaults.selectedClass + '.' + defaults.activeClass).not(this).each(function () {

                // remove edit attr
                $(this).removeAttr('contenteditable');

                // closing select menu
                $(this).removeClass(defaults.activeClass);
                hideMenu($(this).parent(), $('body').children().filter('ul.' + defaults.optionClass));

                // set active option text
                var activeLi = $(this).next().find('li.active').eq(0);
                $(this).text(activeLi.text());
                if (activeLi.attr('isoCode')) {
                    $(this).addClass(activeLi.attr('isoCode'));
                }
            });

            $(this).toggleClass(defaults.activeClass);

            if ($('body').children().filter('ul.' + defaults.optionClass).length == 0) {
                showMenu($(this), $(this).next('ul.' + defaults.optionClass));
            } else {
                hideMenu($(this).parent(), $('body').children().filter('ul.' + defaults.optionClass));
            }
        });
        


        $('body').on('click', '.' + defaults.selectedClass, function (e) {

        	$(this).attr('contenteditable', true);
			// prevent mozilla default actions  
	        $(this).css("-moz-user-select","none");
	        document.execCommand("enableObjectResizing", false, false);
            //placeCaretAtEnd($(this).get(0));
        	//$(this).empty();
            $(this).html("<br/>");

            var input = document.querySelector('.tl_sel_custom_popup_reg_selected.active');

            if ($(this).attr('data-click-state') == 1) {

                if (input != null) {

                    if (e.offsetX > (input.offsetWidth - 20)) {
                        $(this).attr('data-click-state', 0);
                        closeList();
                    }
                }
            } else {
                $(this).attr('data-click-state', 1);
            }

        });

        $('body').on('keydown', '.' + defaults.selectedClass, function (e) {

               
            if (e.keyCode === 13) {

               
                closeList();
                newCloseList();
                    return;
           
                }
            });

        $('body').on('keyup', '.' + defaults.selectedClass, function (e) {
            //split the current value of searchInput
            var data = capitalizeEachWord($(this).text().trim(" "));
            var $list = $('body').children().filter('ul.' + defaults.optionClass);
            var $select = $("#" + $list.data('id'));
            var $styledSelect = $select.next();
            
            //create a jquery object of the rows
            var jo = $list.find('li');//children();

            if (this.value == "") {
                jo.show();
                return;
            }
            
            var contains = false;
            jo.each(function(e) {
                if (isContains($(this), data)) {
                    contains = true;
                    return false;
                }
            });
            
            
            if (contains) {

                //hide all the rows
                jo.hide();

                //Recusively filter the jquery object to get results.
              var filteredArr = jo.filter(function(i, v) {
                    
                    return isContains($(this), data);
                })
                //show the rows that match.
                .show();

                $list.find('li').removeClass('active');
                
                var filteredFirstItem = filteredArr.first();
                filteredFirstItem.addClass('active');

                $select.children().filter(function (i, v) {
                    return $(this).val() == filteredFirstItem.attr('rel');
                }).attr('selected', true);

            } else {
                //$styledSelect.text($select.children('option:selected').eq(0).text());
                jo.hide();
            }
        });
        $('body').on('click', '.' + defaults.optionClass + ' li', function (e) {
            e.stopPropagation();

            var $list = $(this).parents('.' + defaults.optionClass);
            var $select = $("#" + $list.data('id'));
            var $styledSelect = $select.next();

            $list.find('li').removeClass('active');
            $(this).addClass('active');

            $styledSelect.html($(this).text()).removeClass(defaults.activeClass);
            if ($(this).attr('isoCode')) {
                $styledSelect.removeClass();
                $styledSelect.addClass('tl_sel_custom_popup_reg_selected ' + $(this).attr('isoCode'));
            }
            
            $select.val($(this).attr('rel')).trigger('change');

            hideMenu($select.parent(), $list);
        });

        $('body').on('click', function (e) {
            if (!$(e.target).parents('.' + defaults.optionClass).length) {
                closeList();
            }
        });
        $(window).on('resize', function (e) {
            if (!$(e.target).parents('.' + defaults.optionClass).length) {
                closeList();
            }
        });

        var placeCaretAtEnd = function(el) {
            el.focus();
            if (typeof window.getSelection != "undefined"
                && typeof document.createRange != "undefined") {
                var range = document.createRange();
                range.selectNodeContents(el);
                range.collapse(false);
                var sel = window.getSelection();
                sel.removeAllRanges();
                sel.addRange(range);
            } else if (typeof document.body.createTextRange != "undefined") {
                var textRange = document.body.createTextRange();
                textRange.moveToElementText(el);
                textRange.collapse(false);
                textRange.select();
            }
        };

        var capitalizeEachWord = function (str) {
            return str.charAt(0).toUpperCase() + str.slice(1);
        };

        var isContains = function (el, data) {
            if (el.is(":contains('" + data + "')")) {
                return true;
            }
            return false;
        };

        var showMenu = function (elem, menuElem) {
            if (elem.attr('id') == 'custom_MolekulaBetshops') {
                menuElem.css({
                    top: elem.offset().top + elem.outerHeight(),
                    left: elem.offset().left - 150,
                    width: elem.outerWidth() + 150,
                    display: 'block',
                }).appendTo('body');
            } else if (elem.attr('id') == 'custom_secret_question') {//tmp
                menuElem.css({
                    top: elem.offset().top + elem.outerHeight(),
                    left: elem.offset().left - 120,
                    width: elem.outerWidth() + 120,
                    display: 'block',
                }).appendTo('body');
            }else  {
                menuElem.css({
                    top: elem.offset().top + elem.outerHeight(),
                    left: elem.offset().left,
                    width: elem.outerWidth(),
                    display: 'block',
                }).appendTo('body');
            }
        };

        var hideMenu = function (elem, menuElem) {
            elem.find('.tl_sel_custom_popup_reg_options').remove();
            menuElem.hide().appendTo(elem);
        };

        var closeList = function() {

            $('.' + defaults.selectedClass).each(function () {
                var $select = $(this).prev();

                $(this).removeAttr('contenteditable');
                $(this).removeClass(defaults.activeClass);
                $(this).text($select.children('option:selected').eq(0).text());

                var txt = $(this).text($select.children('option:selected').eq(0).text());
              


            });
            
            var $list = $('body').children().filter('ul.' + defaults.optionClass);
            var $listSelect = $('#' + $list.data('id'));

            $listSelect.trigger('change');

            hideMenu($listSelect.parent(), $list);
        };

        var newCloseList = function() {
            var selectValue = $("  .tl_sel_custom_popup_reg_options #mCSB_1_container li.active").text();
                    $("#custom_countryNumber").html(selectValue);

        };

        // heare shoud be go methods
        var methods = {
            refresh: function (options, elem) {
                init(options, elem, true);
            },
            closeList: function() {
                closeList();
            }
        };

        options = options || {};

        if (typeof options.method !== 'undefined') {

            var method = options.method;
            delete options.method;

            if (typeof methods[method] !== 'undefined') {
                methods[method](options, $(this));
            }
        }

        else {
            init(options, $(this));
        }

        return $(this);
    }
});

/*Custom Select Menu End */

function showLoading(event) {
    $(event.target).hide();
    $($(event.target).parent().next()).show();
}

function hideLoading(event) {
    $($(event.target).parent().next()).hide();
    $(event.target).show();
}