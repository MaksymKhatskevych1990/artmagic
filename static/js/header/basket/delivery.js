import { formOrder } from "./order.js?v=2";

document.addEventListener("DOMContentLoaded", () => {
    const notification = document.getElementById('notification');
    const formContainer = document.querySelector('.order-choose__form');
    const btnSubmitOrder = document.querySelector(`[data-submit="btn_Order"]`);
    const paymentRealRadioInput = document.querySelector('#payment_real')
    const paymentRealRadioInputContainer = paymentRealRadioInput.parentElement;

    let selectedDelivery = null;
    let selectedPayment = null;

    // Функция для отображения или скрытия радио-кнопки "У точці видачі"
    const markSelected = (input) => {
        document.querySelectorAll(`input[name="${input.name}"]`).forEach((el) => {
            const label = document.querySelector(`label[for="${el.id}"]`);
            if (label) label.classList.toggle("is-selected", el.checked);
        });
    };

    const updatePaymentRealVisibility = () => {
        if (selectedDelivery === "artmagic_department") {
            paymentRealRadioInputContainer.classList.remove("d-none");
        } else {
            paymentRealRadioInputContainer.classList.add("d-none");
        }
        if (selectedDelivery !== "artmagic_department" && paymentRealRadioInput.checked) {
            paymentRealRadioInput.checked = false;
            markSelected(paymentRealRadioInput);
            formOrder.setSelectedPayment(null);
            selectedPayment = null;
        }
    };



    const updateNotification = () => {
        switch (true) {
            case !selectedDelivery && !selectedPayment:
                notification.textContent = 'Будь ласка, оберіть спосіб доставки й оплати.';
                disableSubmitButton();
                break;
            case !selectedDelivery:
                notification.textContent = 'Будь ласка, оберіть спосіб доставки.';
                disableSubmitButton();
                break;
            case !selectedPayment:
                notification.textContent = 'Будь ласка, оберіть спосіб оплати.';
                disableSubmitButton();
                break;
            default:
                notification.textContent = '';
                enableSubmitButton();
                break;
        }
    };
    
    const disableSubmitButton = () => {
        btnSubmitOrder.setAttribute('disabled', 'disabled');
    };
    
    const enableSubmitButton = () => {
        btnSubmitOrder.removeAttribute('disabled');
    };
    updateNotification();

    const iconsDelivery = document.querySelectorAll('[data-delivery]');

    const orderInputWrap = (fieldName) => document.querySelector(`[data-field="${fieldName}"]`).parentElement;
    const orderInputWraps = document.querySelectorAll('.order__input__wrap');
    orderInputWraps.forEach((inputWrap) => inputWrap.classList.add('d-block'));

    const show = (el) => {
        el.classList.remove('d-none');
        el.classList.add('d-block');
    }

    const hide = (el) => {
        el.classList.remove('d-block');
        el.classList.add('d-none');
    }

    const removeDeliveryActiveClass = () => {
        iconsDelivery.forEach((icon) => {
            const typeOfIcon = icon.dataset.delivery;
            switch (typeOfIcon) {
                case "artmagic_department":
                    icon.setAttribute("src", "/static/assets/basket-icons/artmagic.png");
                    break;
                case "new_post_department":
                case "new_post_packing":
                case "new_post_address":
                    icon.classList.remove('c11');
                    icon.classList.add('c8');
                    break;
                case "ukr_post":
                    icon.classList.remove('c20');
                    icon.classList.add('c8');
                    break;
                    
            }
        });
    }

    const applyDeliveryVisual = (type) => {
        removeDeliveryActiveClass();
        const icon = document.querySelector(`[data-delivery="${type}"]`);
        if (!icon) return;
        switch (type) {
            case "artmagic_department":
                icon.setAttribute("src", "/static/assets/logo/artmagic.png");
                break;
            case "new_post_department":
            case "new_post_packing":
            case "new_post_address":
                icon.classList.remove("c8");
                icon.classList.add("c11");
                break;
            case "ukr_post":
                icon.classList.remove("c8");
                icon.classList.add("c20");
                break;
        }
    };

    document.querySelectorAll('input[name="delivery"]').forEach((input) => {
        input.addEventListener("change", () => {
            if (!input.checked) return;
            selectedDelivery = input.id;
            formOrder.setSelectedDelivery(selectedDelivery);
            applyDeliveryVisual(selectedDelivery);
            markSelected(input);
            updatePaymentRealVisibility();
            updateNotification();
            clearDepartmentQuery();
            updateFormFields();
        });
    });

    const iconsPayment = document.querySelectorAll('[data-payment]');

    const removePaymentActiveClass = () => {
        iconsPayment.forEach((icon) => {
            const typeOfIcon = icon.dataset.payment;
            switch (typeOfIcon) {
                case "liqpay":
                    const pathesLiqpay = icon.children[0].children;
                    pathesLiqpay[0].classList.remove("c14");
                    for (let i = 1; i <= 2; i++) {
                        pathesLiqpay[i].classList.remove("c23");
                        pathesLiqpay[i].classList.add("c6");
                    }
                    break;
                case "payment_card":
                    icon.classList.remove("c20");
                    icon.classList.add("c8");
                    break;
                case "payment_real":
                    icon.setAttribute("src", "/static/assets/basket-icons/oplata-kartoy_grey.png");
                    break;
            }
        });
    }

    const applyPaymentVisual = (type) => {
        removePaymentActiveClass();
        const icon = document.querySelector(`[data-payment="${type}"]`);
        if (!icon) return;
        switch (type) {
            case "liqpay":
                const pathesLiqpay = icon.children[0].children;
                pathesLiqpay[0].classList.add("c14");
                for (let i = 1; i <= 2; i++) {
                    pathesLiqpay[i].classList.remove("c6");
                    pathesLiqpay[i].classList.add("c23");
                }
                break;
            case "payment_card":
                icon.classList.remove("c8");
                icon.classList.add("c20");
                break;
            case "payment_real":
                icon.setAttribute("src", "/static/assets/basket-icons/oplata-kartoy.png");
                break;
        }
    };

    document.querySelectorAll('input[name="payment"]').forEach((input) => {
        input.addEventListener("change", () => {
            if (!input.checked) return;
            selectedPayment = input.id;
            formOrder.setSelectedPayment(selectedPayment);
            applyPaymentVisual(selectedPayment);
            markSelected(input);
            updateNotification();
            updateFormFields();
        });
    });

    document.querySelectorAll(".order-choose label.card-input__icon-wrap").forEach((label) => {
        label.addEventListener("click", () => {
            const input = document.getElementById(label.htmlFor);
            if (!input || input.checked) return;
            input.checked = true;
            input.dispatchEvent(new Event("change", { bubbles: true }));
        });
    });

    const optionPickers = [];

    const bindOptionPicker = (select, { emptyText, maxResults = 30 }) => {
        const root = select.closest(".option-picker");
        const query = root.querySelector(".option-picker__query");
        const list = root.querySelector(".option-picker__list");
        let activeIndex = -1;

        const selectableOptions = () => [...select.options].filter((option) => option.value && option.value !== "null");

        const closeList = () => {
            list.hidden = true;
            list.innerHTML = "";
            activeIndex = -1;
        };

        const placeList = () => {
            const rect = query.getBoundingClientRect();
            const spaceBelow = window.innerHeight - rect.bottom - 12;
            const spaceAbove = rect.top - 12;
            const openUp = spaceBelow < 160 && spaceAbove > spaceBelow;
            const maxHeight = Math.max(120, Math.min(220, openUp ? spaceAbove : spaceBelow));
            list.style.left = `${rect.left}px`;
            list.style.width = `${rect.width}px`;
            list.style.maxHeight = `${maxHeight}px`;
            if (openUp) {
                list.style.top = "auto";
                list.style.bottom = `${window.innerHeight - rect.top + 4}px`;
            } else {
                list.style.bottom = "auto";
                list.style.top = `${rect.bottom + 4}px`;
            }
        };

        const choose = (option) => {
            select.value = option.value;
            query.value = option.textContent.trim();
            select.dispatchEvent(new Event("input", { bubbles: true }));
            select.dispatchEvent(new Event("change", { bubbles: true }));
            closeList();
        };

        const render = (filterText) => {
            const needle = filterText.trim().toLowerCase();
            optionPickers.forEach((picker) => {
                if (picker.list !== list) picker.closeList();
            });
            list.innerHTML = "";
            activeIndex = -1;
            if (list.parentElement !== document.body) document.body.appendChild(list);
            list.hidden = false;
            placeList();

            const available = selectableOptions();
            if (!available.length) {
                list.innerHTML = `<li class="option-picker__empty">${emptyText}</li>`;
                return;
            }

            const ranked = available
                .map((option) => {
                    const text = option.textContent.toLowerCase();
                    return { option, index: needle ? text.indexOf(needle) : 0, starts: Boolean(needle) && text.startsWith(needle) };
                })
                .filter((item) => item.index >= 0);
            if (needle) {
                ranked.sort((a, b) => Number(b.starts) - Number(a.starts) || a.index - b.index);
            }
            const matches = ranked.slice(0, maxResults).map((item) => item.option);
            if (!matches.length) {
                list.innerHTML = `<li class="option-picker__empty">Нічого не знайдено</li>`;
                return;
            }

            matches.forEach((option) => {
                const item = document.createElement("li");
                const button = document.createElement("button");
                button.type = "button";
                button.className = "option-picker__option";
                button.textContent = option.textContent.trim();
                button.addEventListener("mousedown", (event) => event.preventDefault());
                button.addEventListener("click", () => choose(option));
                item.appendChild(button);
                list.appendChild(item);
            });
        };

        query.addEventListener("focus", () => render(""));
        query.addEventListener("click", () => render(""));
        query.addEventListener("input", () => {
            const selected = select.selectedOptions[0];
            if (select.value && select.value !== "null" && query.value.trim() !== selected?.textContent.trim()) {
                select.value = "null";
                select.dispatchEvent(new Event("input", { bubbles: true }));
            }
            render(query.value);
        });
        query.addEventListener("keydown", (event) => {
            const buttons = [...list.querySelectorAll(".option-picker__option")];
            if (event.key === "Escape") {
                closeList();
                return;
            }
            if (!buttons.length || !["ArrowDown", "ArrowUp", "Enter"].includes(event.key)) return;
            event.preventDefault();
            if (event.key === "ArrowDown") activeIndex = Math.min(activeIndex + 1, buttons.length - 1);
            if (event.key === "ArrowUp") activeIndex = Math.max(activeIndex - 1, 0);
            if (event.key === "Enter") {
                (buttons[activeIndex] || buttons[0]).click();
                return;
            }
            buttons.forEach((button, index) => button.classList.toggle("is-active", index === activeIndex));
            buttons[activeIndex]?.scrollIntoView({ block: "nearest" });
        });

        new MutationObserver(() => {
            query.value = "";
            closeList();
        }).observe(select, { childList: true });

        const picker = {
            root,
            query,
            list,
            closeList,
            placeList,
            clear() { query.value = ""; closeList(); },
        };
        optionPickers.push(picker);
        return picker;
    };

    const areaPicker = bindOptionPicker(document.querySelector('[data-field="area"]'), {
        emptyText: "Області ще завантажуються",
    });
    const cityPicker = bindOptionPicker(document.querySelector('[data-field="city"]'), {
        emptyText: "Спочатку оберіть область",
    });
    const departmentPicker = bindOptionPicker(document.querySelector('[data-field="department"]'), {
        emptyText: "Спочатку оберіть місто",
    });
    const departmentQuery = departmentPicker.query;

    const clearDepartmentQuery = () => {
        areaPicker.clear();
        cityPicker.clear();
        departmentPicker.clear();
    };

    document.addEventListener("click", (event) => {
        optionPickers.forEach((picker) => {
            const insideField = event.target.closest(".option-picker") === picker.root;
            const insideList = picker.list.contains(event.target);
            if (!insideField && !insideList) picker.closeList();
        });
    });

    document.querySelector(".basket__modal__body")?.addEventListener("scroll", () => {
        optionPickers.forEach((picker) => {
            if (!picker.list.hidden) picker.placeList();
        });
    }, true);

    document.getElementById("basket__modal")?.addEventListener("hidden.bs.modal", () => {
        optionPickers.forEach((picker) => picker.closeList());
    });

    const updateFormFields = () => {
        const fieldsToShow = [];

        if (selectedDelivery === "ukr_post") {
            fieldsToShow.push("fullName", "clientPhone", "address", "email");
        }
        if(selectedDelivery === "artmagic_department"){
            fieldsToShow.push("fullName", "clientPhone", "email");
        }
        if (selectedDelivery === "new_post_packing" || selectedDelivery === "new_post_department") {
            fieldsToShow.push("fullName", "clientPhone", "area", "city", "email", "department");
            departmentQuery.placeholder = selectedDelivery === "new_post_packing"
                ? "Номер або адреса поштомата"
                : "Номер або адреса відділення";
        }
        if (selectedDelivery === "new_post_address" ){
            fieldsToShow.push("fullName", "clientPhone","address", "area", "city", "email");
        }




        formOrder.userAuthDefaultData()


        orderInputWraps.forEach((wrap) => {
            const fieldName = wrap.querySelector('.order__input').dataset.field;
            if (fieldsToShow.includes(fieldName)) {
                show(wrap);
            } else {
                hide(wrap);
            }
        });
    };

    // Initialize form fields with null values
    const initializeFormFields = () => {
        document.querySelector('[data-field="fullName"]').value = '';
        document.querySelector('[data-field="clientPhone"]').value = '';
        document.querySelector('[data-field="email"]').value = '';
        document.querySelector('[data-field="address"]').value = '';
        document.querySelector('[data-field="area"]').value = 'null';
        document.querySelector('[data-field="city"]').value = 'null';
    };

    updatePaymentRealVisibility(); // Обновить видимость "У точці видачі"
    initializeFormFields();
    updateFormFields();
});




