var CANVAS_ELEMENT_TYPES = {
    Title: 1,
    Description: 2,
    Image: 3,
    Button: 4,
    Dismissible: 5
}

var MEDIA_TYPE = {
    Image: 1,
    Video: 2,
}

function renderAbsoluteElements($container, sectionData, baseUrl, isBody = false) {
    if (!sectionData || !sectionData.Elements) return;

    $container.css({ position: 'relative', width: '100%' });

    if (sectionData.ContentOffsetHeight && typeof sectionData.ContentOffsetHeight === 'number' && sectionData.ContentOffsetHeight > 0 && isBody) {
        $container.css({ maxHeight: sectionData.ContentOffsetHeight });
    }

    let maxBottomPx = 0;

    sectionData.Elements.forEach((el, index) => {
        const layout = JSON.parse(el.Layout);

        const leftPx = layout.x * 4;
        const widthPx = layout.w * 4;
        const topPx = layout.y * 4;
        const heightPx = layout.h * 4;

        if (topPx + heightPx > maxBottomPx) {
            maxBottomPx = topPx + heightPx;
        }

        const htmlContent = buildElement(el, baseUrl);

        const $wrapper = $(`
                <div style="
                    position: absolute;
                    left: ${leftPx}px;
                    top: ${topPx}px;
                    width: ${widthPx}px;
                    height: ${heightPx}px;
                    z-index: ${index + 1};
                    box-sizing: border-box;
                ">
                    ${htmlContent}
                </div>
            `);

        $container.append($wrapper);
    });

    $container.css('height', maxBottomPx + 'px !important');
}

function buildElement(el, baseUrl, ) {
    const content = el.ElementContents?.[0];
    if (!content) return "";

    let html = "";

    let cleanStyles = el.InlineStyle ? el.InlineStyle.replace(/'/g, "").replace(/,/g, ";") : "";

    if (el.Icon) {
        html += `<i class="dynamic_popup_canvas_icon" class="${el.Icon}"></i>`;
    }

    if (el.ElementType === CANVAS_ELEMENT_TYPES.Title) {
        html += `<div class="dynamic_popup_canvas_title" style="width:100%; height:100%; ${cleanStyles}">${content.Title || ''}</div>`;
    }

    if (el.ElementType === CANVAS_ELEMENT_TYPES.Description) {
        html += `<div class="dynamic_popup_canvas_description" style="width:100%; height:100%; ${cleanStyles}">${content.DescriptionHtml || ''}</div>`;
    }

    if (el.ElementType === CANVAS_ELEMENT_TYPES.Image) {
        if (content.MediaType === MEDIA_TYPE.Image) {
            html += `<img class="dynamic_popup_canvas_image" src="${baseUrl}${content.MediaUrl}" style="width:100%; height:100%; display:block; ${cleanStyles}">`;
        }
        else if (content.MediaType === MEDIA_TYPE.Video) {
            html += `<video class="dynamic_popup_canvas_video" src="${baseUrl}${content.MediaUrl}" style="width:100%; height:100%; ${cleanStyles}" controls></video>`;
        }
    }

    if (el.ElementType === CANVAS_ELEMENT_TYPES.Button) {
        html += `<button class="dynamic_popup_canvas_button" style="width:100%; height:100%; ${cleanStyles}" onclick="location.href='${content.RedirectUrl}'">${content.ButtonText}</button>`;
    }

    if (el.ElementType === CANVAS_ELEMENT_TYPES.Dismissible) {
        html += `
            <label class="checkBox_label" style="display:flex; width:100%; height:100%; align-items:center;">
                <input class="checkBox_input popup-dismiss-checkbox" type="checkbox" id="" name="" data-role="none">
                <span class="checkBox_icon"></span>
                <span style="${cleanStyles}" class="checkBox_text">Don't show again</span>
            </label>
        `;
    }

    return `<div class="dynamic_popup_canvas_element" style="width:100%; height:100%;">${html}</div>`;
}