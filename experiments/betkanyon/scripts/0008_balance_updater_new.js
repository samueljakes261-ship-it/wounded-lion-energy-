var BalanceUpdater = {
    PlayerId: 0,
    _intervalId: null,
    _isRunning: false,
    _updateInterval: null,
    start: function () {
        CurrencyManager.init(this.PlayerId);
        if (this._isRunning)
            return;
        this._intervalId = setInterval(this.getBalanceAmount.bind(this), this._updateInterval);
        this._isRunning = true;
    },

    tryUpdateStatus: function () {
        var t = this;

        if (this._isRunning) {
            return ;
        }

        if (t._intervalId) {
            clearTimeout(t._intervalId);
        }

        $.ajax( {
            url: '/Common/GetLoginStatus',
            type: 'post',
            dataType: 'json',
            success: function (data) {
                if ((typeof regClicked === 'undefined' || !regClicked) && data && data.Reload == "Reload") {
                    if (document.getElementById('js_reg_form') != null) {
                        return;
                    }
                    document.location.reload();
                } else {
                    t._intervalId = setTimeout(t.tryUpdateStatus.bind(t), 60000);
                }
            }
        });
    },
    checkLoginStatus: function (data) {
        const cachedStatus = sessionStorage.getItem('_stChecked');
        if (!cachedStatus || cachedStatus != 'true') {
            getTelemetryData(data, 'v').then((result) => {
                checkStatus(result.data);
            }).catch((err) => {
                checkStatus(err);
            });
        }
        function checkStatus(param) {
            $.ajax({
                url: '/common/checkloginstatus',
                type: 'post',
                data: { param: param },
                dataType: 'json',
                success: function (data) {
                    sessionStorage.setItem('_stChecked', true);
                }
            });
        }
    },
    stop: function () {
        clearInterval(this._intervalId);
        this._isRunning = false;
    },

    getBalanceAmount: function () {
        var self = this;

        if (this.PlayerId > 0) {
            $.ajax( {
                url: '/Wallet/GetBalanceStatus',
                type: 'post',
                dataType: 'json',
                dataFilter: function (data, type) {
                    if (type === 'json') {
                        return data.replace(/:\s*([-+]?\d+\.\d+)([,\s}])/g, ': "$1"$2');
                    }
                    return data;
                },
                success: function (data, text, request) {
                    self.onBalanceStatus(data);
                    responsibleGamingChecks(data);
                    if (data.CheckActivity && typeof checkActivity == 'function') {
                        checkActivity();
                    }
                }
            });
        }
    },

    onBalanceStatus: function (data) {
        CurrencyManager.init(this.PlayerId);
        if (data.Success) {
            if (window.js_available_persian_balance) {
                window.js_available_persian_balance.innerText = toPersianDigit(CurrencyManager.format(data.Data.AvailableBalance, data.Data.CurrencyId));

            } else if (window.js_available_balance) {
                window.js_available_balance.innerText = CurrencyManager.format(data.Data.AvailableBalance, data.Data.CurrencyId);
            }

            if (window.js_persian_bonus_balance) {
                if (data.Data.BonusBalance != 0) {
                    window.js_persian_bonus_balance.innerHTML = toPersianDigit(CurrencyManager.format(data.Data.BonusBalance, data.Data.CurrencyId));
                    window.bonusPersianBalanceCont.classList.remove('hidden');
                } else {
                    window.bonusPersianBalanceCont.classList.add('hidden');
                }
            } else if (window.js_bonus_balance) {
                if (data.Data.BonusBalance != 0) {
                    window.js_bonus_balance.innerHTML = CurrencyManager.format(data.Data.BonusBalance, data.Data.CurrencyId);
                    window.bonusBalanceCont.classList.remove('hidden');
                } else {
                    window.bonusBalanceCont.classList.add('hidden');
                }
            }

            if (data.Data.SportBonusBalance && window.lblSportBalance) {
                window.lblSportBalance.innerText = data.Data.SportBalance;
            }
        } else if (data.Reload) {
            document.location.reload();
        }
    }
};
function responsibleGamingChecks(data) {
    var showRealityCheckPopup = data.ShowRealityCheckPopup;
    if (showRealityCheckPopup == 'yes' && (typeof _allowRealityCheck == 'undefined' || _allowRealityCheck == true)) {
        getRealityCheckPopupInfo();
    }
}
function toPersianDigit(balance) {
    var persianBalance = balance.toString();
    persianBalance = persianBalance.replace(/0/g, '۰');
    persianBalance = persianBalance.replace(/1/g, '۱');
    persianBalance = persianBalance.replace(/2/g, '۲');
    persianBalance = persianBalance.replace(/3/g, '۳');
    persianBalance = persianBalance.replace(/4/g, '۴');
    persianBalance = persianBalance.replace(/5/g, '۵');
    persianBalance = persianBalance.replace(/6/g, '۶');
    persianBalance = persianBalance.replace(/7/g, '۷');
    persianBalance = persianBalance.replace(/8/g, '۸');
    persianBalance = persianBalance.replace(/9/g, '۹');
    return persianBalance;
}
