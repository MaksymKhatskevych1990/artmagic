function createCheckoutRequestId() {
    if (window.crypto && typeof crypto.randomUUID === "function") {
        return crypto.randomUUID();
    }
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
        const random = Math.random() * 16 | 0;
        const value = char === "x" ? random : (random & 0x3 | 0x8);
        return value.toString(16);
    });
}

function escapeCheckoutHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

class Form {
    constructor(obj, patterns, formName, alertCl, ...args) {
        this.formData = Object.fromEntries(
            Object.keys(obj).map(key => [
                key,
                {
                    value: "",
                    patterns: patterns[key] || []
                }
            ])
        );
        const [productManager, basket, userData, bootstrap] = args;
        this.productManager = productManager ?? null;
        this.alert = alertCl ?? null;
        this.basket = basket ?? null;
        this.userData = userData ?? null;
        this.bootstrap = bootstrap ?? null;
        this.initObj = obj;
        this.formName = formName;
        this.dataSubmitBtn = document.querySelector(`button[data-submit="btn_${formName}"]`);
        this.successLabel = document.querySelector("div#successMessage");
        this.errorLabel = document.querySelector("div#errorMessage");
        this.selectedBasketObj = {
            selectedDelivery: null,
            selectedPayment: null
        }
    }

    getField(fieldName) {
        return document.querySelector(`input[data-field="${fieldName}"]`) 
        ?? document.querySelector(`textarea[data-field="${fieldName}"]`) 
        ?? document.querySelector(`select[data-field="${fieldName}"]`); 
    }

    errorMessageElement(fieldName) {
        return document.querySelector(`p[data-error="${fieldName}"]`);
    }

    editField(fieldName) {
        const target = this.getField(fieldName);
        target.disabled = !target.disabled;
        target.focus();
        target.setSelectionRange(target.value.length, target.value.length);
    }

    clearField(fieldName, triggerInpCond = true) {
        this.getField(fieldName).value = "";
        if (triggerInpCond) this.triggerInput(fieldName);
    }

    triggerInput(fieldName) {
        if(fieldName == "description" || fieldName == "amount")
            return;
        const errorElem = this.errorMessageElement(fieldName);  
        this.formData[fieldName].value = this.getField(fieldName).value;
        return !this.validateField(fieldName, errorElem);
    }

    validateField(fieldName, errorElem) {
        const field = this.getField(fieldName);
        const fieldValue = field.value;
        const patterns = this.formData[fieldName].patterns;

        for (let patternObj of patterns) {
            const regex = new RegExp(patternObj.rule);
            if (!regex.test(fieldValue)) {
                field.classList.add("invalid-input");
                errorElem.classList.remove("error-message-hidden");
                errorElem.classList.add("error-message");
                errorElem.textContent = patternObj.errorMsg;
                return false;
            }
        }

        if (errorElem) {
            field.classList.remove("invalid-input");
            errorElem.classList.remove("error-message");
            errorElem.classList.add("error-message-hidden");
            errorElem.textContent = '';
        }
        return true;
    }

    async initForm(formContainerId, obj, path, methodType, msgObj, animDuration, clearCond = true) {
        const formContainer = document.getElementById(formContainerId);

        this.userAuthDefaultData();

    

        const fields = formContainer.querySelectorAll("[data-field]");
        fields.forEach((field) => field.addEventListener("input", (e) => 
            this.triggerInput(field.dataset.field)
        ));



        const areaInputWrap = this.orderInputWrap("area");

        this.updateAreaOptions(areaInputWrap);

        const cityInputWrap = this.orderInputWrap("city");
        const departmentInputWrap = this.orderInputWrap("department");

        this.fetchSomeOptions(areaInputWrap, cityInputWrap, "get_cities", "region_ref", "-- Оберіть Місто --", "cities", undefined, this.areasDataWithNullField);
        this.fetchSomeOptions(cityInputWrap, departmentInputWrap, "get_branches_and_postomats", "city_ref", "-- Оберіть відділення", "branches", this.filterData)
            
        // Добавляем чуток для новой модалки для заказа (обработка событий)
        if(this.bootstrap){
            const successModalBtnClose = document.querySelector("#successModal .btn-close");
            successModalBtnClose.addEventListener("click", () => this.hideHoleModals());
            const actionButton = document.querySelector('#successModalBtn');
            actionButton.addEventListener("click", () => this.hideHoleModals());
        }


        this.dataSubmitBtn.addEventListener("click", async (e) => {
            e.preventDefault();
            if (this.checkoutInFlight) {
                return;
            }
            this.checkoutInFlight = true;
            const buttonLabel = this.dataSubmitBtn.textContent;
            this.dataSubmitBtn.disabled = true;
            this.dataSubmitBtn.textContent = "Обробка...";
            this.showModalLoader();

            let succeeded = false;
            let liqpayWindow = null;
            try {
                let invalid = false;
                Object.keys(this.formData).forEach((key) => {
                    if (this.triggerInput(key)) {
                        invalid = true;
                    }
                });
                if (invalid) {
                    throw new Error("Будь ласка заповніть поля форми");
                }
                if (!this.selectedBasketObj.selectedDelivery || !this.selectedBasketObj.selectedPayment) {
                    throw new Error("Оберіть спосіб доставки та оплати");
                }
                if (!this.productManager) {
                    throw new Error("Відсутні продукти у кошику.");
                }
                if (this.selectedBasketObj.selectedPayment === "liqpay") {
                    const windowName = `artmagic_liqpay_${Date.now()}`;
                    liqpayWindow = window.open("about:blank", windowName);
                    if (!liqpayWindow) {
                        throw new Error("Дозвольте спливаючі вікна для переходу до LiqPay.");
                    }
                    liqpayWindow.document.title = "ArtMagic — LiqPay";
                    liqpayWindow.document.body.textContent = "Підготовка сторінки оплати…";
                }

                const quote = await this.productManager.refreshStock();
                this.basket.renderBasket();
                if (!this.productManager.getProducts().length) {
                    throw new Error("Деякі товари недоступні або кошик порожній.");
                }
                const confirmationQuote = quote.changed
                    ? quote
                    : this.productManager.unconfirmedQuote;
                if (this.productManager.stockConfirmationRequired && confirmationQuote) {
                    const confirmed = await this.askStockConfirmation(confirmationQuote);
                    if (!confirmed) {
                        this.checkoutRequestId = null;
                        this.checkoutCartKey = null;
                        throw new Error("Оформлення скасовано. Перевірте кошик.");
                    }
                    this.productManager.confirmStockQuote();
                }

                const requestId = this.ensureCheckoutRequestId();
                const payload = {
                    ...this.mapedFormData(obj),
                    ...this.selectedBasketObj,
                    products: this.productManager.filterProductsByQuantity(this.productManager.getProducts()),
                    client_request_id: requestId,
                    confirmed_fingerprint: this.productManager.lastFingerprint,
                };
                if (!payload.products.length) {
                    throw new Error("Відсутні продукти у кошику.");
                }

                let result = null;
                for (let attempt = 0; attempt < 3; attempt++) {
                    result = await this.postCheckout(payload);
                    if (result.status !== "stock_changed") {
                        break;
                    }
                    this.productManager.applyRefresh(result.cart);
                    this.productManager.lastFingerprint = result.cart.fingerprint;
                    this.productManager.stockConfirmationRequired = true;
                    this.productManager.unconfirmedQuote = result.cart;
                    this.basket.renderBasket();
                    const confirmed = await this.askStockConfirmation(result.cart);
                    if (!confirmed) {
                        this.checkoutRequestId = null;
                        this.checkoutCartKey = null;
                        throw new Error("Оформлення скасовано. Перевірте кошик.");
                    }
                    this.productManager.confirmStockQuote();
                    payload.products = this.productManager.filterProductsByQuantity(this.productManager.getProducts());
                    payload.confirmed_fingerprint = result.cart.fingerprint;
                }
                if (!result || result.status !== "success" || !result.orderNumber) {
                    throw new Error((result && result.message) || "Не вдалося оформити замовлення");
                }

                if (result.formHtml) {
                    const liqpayFormContainer = document.getElementById("liqpayForm");
                    liqpayFormContainer.innerHTML = result.formHtml;
                    const paymentForm = liqpayFormContainer.querySelector("form");
                    if (!paymentForm || !liqpayWindow || liqpayWindow.closed) {
                        throw new Error("Не вдалося відкрити LiqPay. Повторіть спробу з тим самим замовленням.");
                    }
                    paymentForm.target = liqpayWindow.name;
                    paymentForm.submit();
                } else if (liqpayWindow && !liqpayWindow.closed) {
                    liqpayWindow.close();
                }
                succeeded = true;
                this.checkoutRequestId = null;
                this.checkoutCartKey = null;
                this.hideModalLoader();
                if (clearCond) {
                    this.clearForm(this.initObj);
                    const selectors = document.querySelectorAll("select");
                    selectors.forEach((el) => el.value = null);
                    this.userAuthDefaultData();
                    this.productManager.clearStorageProducts();
                    this.productManager.clearProducts();
                    this.productManager.stockReady = false;
                    this.basket.renderBasket();
                }
                this.hideHoleModals();
                if (this.showSuccessModal) {
                    const paymentNote = result.formHtml
                        ? "<br>Завершіть оплату у відкритій вкладці."
                        : "<br><br>Наш менеджер зв'яжеться із вами найближчим часом";
                    this.showSuccessModal(
                        "Успіх! Замовлення прийнято",
                        `<p class="text-center">Супер, Ваше замовлення №${result.orderNumber} прийнято${paymentNote}</p>`
                    );
                }
            } catch (err) {
                if (liqpayWindow && !liqpayWindow.closed) {
                    liqpayWindow.close();
                }
                this.hideModalLoader();
                this.alert("err", err.message || "Не вдалося перевірити наявність товарів. Спробуйте ще раз.", animDuration);
            } finally {
                this.checkoutInFlight = false;
                this.dataSubmitBtn.disabled = this.dataSubmitBtn.dataset.stockBlocked === "1";
                this.dataSubmitBtn.textContent = buttonLabel;
                if (succeeded) {
                    this.hideModalLoader();
                }
            }
        });
    
    }

    async fetchData(path, methodType, data) {
        return fetch(`${PROTOCOL}://${HOST}:${PORT}/${path}`, {
            method: methodType,
            mode: "cors",
            body: JSON.stringify(data),
            headers: {
                'X-CSRFToken': this.getCookie("csrftoken")
            },
        }).then((data) => data.json());
    }

    getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let cookie of cookies) {
                cookie = cookie.trim();
                if (cookie.startsWith(`${name}=`)) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    mapedFormData(obj) {
        return Object.fromEntries(Object.entries(this.formData).map(([key, { value }]) => [obj[key] || key, value]));
    }

    clearForm(obj) {
        Object.keys(obj).forEach((key) => this.clearField(key, false));
    }

    async fetchNewPostAPIData(pathName, query = ""){
        this.showModalLoader();
        const path = `api/${pathName}`
        try {
            const response = await fetch(`${PROTOCOL}://${HOST}:${PORT}/delivery/${path}?${query}`,
                {
                    method: "GET",
                    mode: "cors",
                    headers: {
                        "Accept": "application/json"
                    }
                }
            );
            return await response.json();
        } finally {
            this.hideModalLoader();
        }
    }

    orderInputWrap(fieldName){
        return document.querySelector(`[data-field="${fieldName}"]`);
    }

    async fetchSomeOptions(triggerInputWrap, containerInputWrap, url, queryKey, nullElementText, dataKey, filtrationFunc){
        triggerInputWrap.addEventListener("change", async () => {
            if(triggerInputWrap.value != "null"){
                const nullElement = containerInputWrap.querySelector("option");
                let data;
                try {
                    const payload = await this.fetchNewPostAPIData(url, `${queryKey}=${triggerInputWrap.value}`);
                    data = payload?.[dataKey];
                } catch (error) {
                    console.error(error);
                    return;
                }
                if (!Array.isArray(data)) return;

                const filterDepartment = (dataArr, key) => filtrationFunc(dataArr, key, value => value.startsWith("Відділення"));
                const filterPayment = (dataArr, key) => filtrationFunc(dataArr, key, value => !value.startsWith("Відділення"));
                if(filtrationFunc && this.selectedBasketObj.selectedDelivery === "new_post_department")
                    data = filterDepartment(data, "Description");
                if(filtrationFunc && this.selectedBasketObj.selectedDelivery === "new_post_packing")
                    data = filterPayment(data, "Description");
                
                containerInputWrap.innerHTML = "";  
                nullElement.value = null;
                nullElement.textContent = nullElementText;
                containerInputWrap.appendChild(nullElement);
                data.forEach((city) => {
                    const element = document.createElement("option");
                    element.value = city.Ref;
                    element.textContent = city.Description;
                    containerInputWrap.appendChild(element);
                })
            } 
        });
    }

    clearOptions = (selectElement) => {
        selectElement.innerHTML = "";
    };

    async updateAreaOptions(container){
        const areasData = (await this.fetchNewPostAPIData("get_regions")).regions;
        areasData.forEach((area) => {
            const element = document.createElement("option");
            element.value = area.Ref;
            element.textContent = area.Description;
            
            container.appendChild(element);
        });
    }

    setSelectedDelivery(value){
        this.selectedBasketObj = {...this.selectedBasketObj, selectedDelivery: value};
        this.resetSelectElements();
    }

    setSelectedPayment(value){
        this.selectedBasketObj = {...this.selectedBasketObj, selectedPayment: value};
    }

    filterData(data, key, condition){
        return data.filter((obj) => condition(obj[key]))
    }

    resetSelectElements() {
        // Находим все элементы select в форме
        const form = document.getElementById('orderForm');
        const selects = form.querySelectorAll('select');

        // Устанавливаем значение каждого select на null
        selects.forEach(select => {
            select.value = 'null';
        });
    }

    getCurrentDateTime() {
        const now = new Date();
        
        // Форматирование компонентов даты и времени
        const day = String(now.getDate()).padStart(2, '0');
        const month = String(now.getMonth() + 1).padStart(2, '0'); // Месяцы начинаются с 0
        const year = String(now.getFullYear()).slice(-2);
        
        const hours = String(now.getHours()).padStart(2, '0');
        const minutes = String(now.getMinutes()).padStart(2, '0');
        const seconds = String(now.getSeconds()).padStart(2, '0');
        
        // Форматирование даты и времени в строку
        const formattedDateTime = `${day}.${month}.${year} ${hours}:${minutes}:${seconds}`;
        
        return formattedDateTime;
    }

    userAuthDefaultData(){
        if (this.userData && this.userData.get("status") === "1") {
            this.formData = Object.fromEntries(
                Object.entries(this.formData).map(([key, value]) => {
                    // Получаем значение из userData, если оно есть, иначе ""
                    let newValue = this.userData.has(key) ? this.userData.get(key) : "";
        
                    // Если значение - один пробел или только пробелы, устанавливаем пустую строку
                    if (newValue.trim() === "") {
                        newValue = "";
                    }
        
                    // Обновляем поле формы
                    if (this.userData.has(key)) {
                        this.getField(key).value = newValue;
                    }
        
                    return [key, { ...value, value: newValue }];
                })
            );
        }
        
    }

    showModalLoader(){
        document.getElementById("basket-modal-content").style.display = "flex";
    }

    hideModalLoader(){
        document.getElementById("basket-modal-content").style.display = "none"
    }

    showSuccessModal(title, content) {
        // Изменяем заголовок модалки
        const modalTitle = document.getElementById('successModalLabel');
        modalTitle.textContent = title;
    
        // Изменяем содержимое модалки
        const modalBody = document.getElementById('successModalBody');
        modalBody.innerHTML = content;
    
        // Открываем новую модалку
        const successModal = new bootstrap.Modal(document.getElementById('successModal'), {
            backdrop: false, // Модалка без закрытия кликом вне окна 
            focus: false  
        });
        successModal.show();
        


        
        
    }

    ensureCheckoutRequestId() {
        const key = this.productManager.getProducts()
            .map((product) => `${product.id}:${(Number(product.quantity) || 0) + (Number(product.preorder) || 0)}`)
            .sort()
            .join("|");
        if (this.checkoutCartKey !== key || !this.checkoutRequestId) {
            this.checkoutCartKey = key;
            this.checkoutRequestId = createCheckoutRequestId();
        }
        return this.checkoutRequestId;
    }

    async postCheckout(payload) {
        let response;
        try {
            response = await fetch(`${PROTOCOL}://${HOST}:${PORT}/cart/checkout/`, {
                method: "POST",
                mode: "cors",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": this.getCookie("csrftoken"),
                },
                body: JSON.stringify(payload),
            });
        } catch (error) {
            throw new Error("Не вдалося перевірити наявність товарів. Спробуйте ще раз.");
        }
        let data = null;
        try {
            data = await response.json();
        } catch (error) {
            throw new Error("Не вдалося оформити замовлення");
        }
        if (response.status === 409 && data.status === "stock_changed") {
            return data;
        }
        if (!response.ok) {
            throw new Error(data.message || "Не вдалося оформити замовлення");
        }
        return data;
    }

    askStockConfirmation(cart) {
        const lines = (cart.items || []).map((item) => {
            const name = escapeCheckoutHtml(item.name || `Товар ${item.id}`);
            if (item.unavailable) {
                const reason = item.reason === "disabled" ? "товар недоступний" : "товар не знайдено";
                return `<li>${name}: ${reason}</li>`;
            }
            const notes = [];
            if (item.price_changed) {
                notes.push(`нова ціна ${item.unit_price} грн`);
            }
            if (item.stock_changed) {
                notes.push(`зі складу ${item.quantity}, під замовлення ${item.preorder}, доступно ${item.available}`);
            }
            return notes.length ? `<li>${name}: ${notes.join("; ")}</li>` : "";
        }).join("");
        this.showConfirmationModal(
            "Зміна наявності або ціни",
            `<p>Перевірте кошик перед оформленням.</p><ul>${lines}</ul><p>Сума зі складу: ${cart.total} грн</p><p>Сума попереднього замовлення: ${cart.preorder_total} грн</p>`
        );
        const button = document.getElementById("confirmChoices");
        const modalElement = document.getElementById("confirmationModal");
        return new Promise((resolve) => {
            const onHide = () => {
                button.removeEventListener("click", onConfirm);
                resolve(false);
            };
            const onConfirm = (event) => {
                event.preventDefault();
                modalElement.removeEventListener("hidden.bs.modal", onHide);
                button.removeEventListener("click", onConfirm);
                resolve(true);
                const ModalApi = typeof bootstrap !== "undefined" ? bootstrap : this.bootstrap;
                ModalApi.Modal.getOrCreateInstance(modalElement).hide();
            };
            modalElement.addEventListener("hidden.bs.modal", onHide, { once: true });
            button.addEventListener("click", onConfirm);
        });
    }

    hideHoleModals(){
        const ModalApi = (typeof bootstrap !== "undefined" && bootstrap.Modal) ? bootstrap : this.bootstrap;
        document.querySelectorAll('.modal.show').forEach(modal => {
            const instance = ModalApi && ModalApi.Modal ? ModalApi.Modal.getInstance(modal) : null;
            if (instance) {
                instance.hide();
            }
        });
        const backdrops = document.querySelectorAll('.modal-backdrop');
        backdrops.forEach((backdrop) => {
            if (backdrop){
                backdrop.remove(); // Remove the backdrop element from the DOM
            }
                
        })
        if(window.location.pathname == "/")
            return
        setTimeout(() => window.location.href = "/", 10000);
    }

    showConfirmationModal(title, content) {
        // Изменяем заголовок модалки
        const modalTitle = document.getElementById('confirmationModalLabel');
        modalTitle.textContent = title;
    
        // Изменяем содержимое модалки
        const modalBody = document.getElementById('confirmationModalBody');
        modalBody.innerHTML = content;
        
        // Открываем новую модалку
        const confirmationModal = new bootstrap.Modal(document.getElementById('confirmationModal'), {
            backdrop: false, // Модалка без закрытия кликом вне окна     
            focus: false 
        });
        confirmationModal.show();
        
        return confirmationModal;
    }

    async showProductListModal(products) {
        
        return new Promise((resolve) => {

            

            // Создаем содержимое модального окна с продуктами
            let modalContent = '<div class="confirmation-modal__product-list">';
            products.forEach(product => {
                const showOptions = product.available !== 0 ?
                `<option value="buyAvailable">Купити ${product.available}</option>
                <option value="buyAndPreorder">Купити ${product.available} й дозамовити ${product.quantity - product.available}</option>
                <option value="cancel">Відмовитись від товару</option>`
                :  `<option value="buyAndPreorder">Замовити ${product.quantity}</option>
                <option value="cancel">Відмовитись від товару</option>`
                modalContent += `
                    <div class="confirmation-modal__product-item">
                        <div class="confirmation-modal__product-image-wrap">
                            <img src="${product.image}" alt="${product.name}" class="confirmation-modal__product-image"/>
                        </div>
                        <p>Товар: ${product.name}</p>
                        <p>Артикул: ${product.model}</p>
                        <p>На складі доступно: ${product.available}</p>
                        <p>Ви замовили: ${product.quantity}</p>
                        <div class="confirmation-modal__product-action-wrap"> 
                            <p>Оберіть дію:</p>
                            <select class="confirmation-modal__product-action" data-product-id="${product.id}">
                                `+ showOptions + `
                            </select>
                        </div>
                    </div>
                `;
                
            });
            
        
            // Показываем модальное окно
            const modalInstance = this.showConfirmationModal("Недостатньо товарів на складі", modalContent);
            const images = document.querySelectorAll(".confirmation-modal__product-image")
            rerenderImage(images);

            const modalElement = document.getElementById("confirmationModal");

            modalElement.addEventListener('hidden.bs.modal', () => {
                this.hideModalLoader();
                this.basketModalCarousel.enable();
                if(this.basketModalCarousel) this.basketModalCarousel.slideTo(0);
            });

            modalElement.style.top = '0';

            // Обработчик на кнопку подтверждения
            if(document.getElementById("confirmChoices"))
            document.getElementById("confirmChoices").addEventListener("click", () => {
                const actions = Array.from(document.querySelectorAll(".confirmation-modal__product-action")).map(select => {
                    return {
                        id: select.dataset.productId,
                        action: select.value
                    };
                });
                this.hideModalLoader();
                this.hideModalsAfterConfirmation();
                modalInstance.hide();
                this.basketModalCarousel.enable();
                const footerBasketModalBtns = document.querySelector(".modal-footer__btns").children;
                Array.from(footerBasketModalBtns).forEach(b => b.classList.remove('active'));
                footerBasketModalBtns[0].classList.add('active');
                this.basket.renderBasket();
                resolve(actions);
            });
        });

        
    }

    hideModalsAfterConfirmation(){
        const modal = document.getElementById('confirmationModal');

        this.bootstrap.Modal.getInstance(modal).hide();
        const backdrops = document.querySelectorAll('.modal-backdrop');
        if(backdrops.length > 2)
            backdrops[0].remove();
    }
   

}
