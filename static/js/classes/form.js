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
            this.showModalLoader();
        
            let emptyForm = false;
            Object.keys(this.formData).forEach(key => this.triggerInput(key));
        
            const submitedFormData = { ...this.mapedFormData(obj), ...this.selectedBasketObj };
            submitedFormData.amount = this.productManager.allProductsTotalPrice(this.productManager.priceOutputFn, 2);
        
            if (this.productManager !== null) 
                submitedFormData.products = this.productManager.filterProductsByQuantity(this.productManager.getProducts());
        
            const productsExistCondition = submitedFormData.products && submitedFormData.products.length === 0;
        

            try {
                if (productsExistCondition || submitedFormData.products.length === 0) 
                    throw new Error("Відсутні продукти у кошику.");

                // Создание заказа после всех проверок и подтверждений
                if (this.selectedBasketObj.selectedPayment == "liqpay") {
                    this.formData.description = `
                        ФОП Чикольба Т.Ю.
                        Час замовлення: ${this.getCurrentDateTime()}
                        Продукти: 
                        ${this.productManager.getProductsInfo()}
                    `;
        
                    const body = this.formData;
                    body.amount = this.productManager.allProductsTotalPrice(this.productManager.priceOutputFn, 2);
                    body.products = this.productManager.filterProductsByQuantity(this.productManager.getProducts());
                    body.selectedDelivery = this.selectedBasketObj.selectedDelivery;
                    body.selectedPayment = this.selectedBasketObj.selectedPayment;

                    try {
                        const { formHtml, orderNumber } = await this.fetchData(`payment/create/`, "POST", body);

                        submitedFormData.orderNumber = orderNumber;
                        const liqpayFormContainer = document.getElementById('liqpayForm');
                        liqpayFormContainer.innerHTML = formHtml;
                        liqpayFormContainer.querySelector('form').addEventListener("submit", (e) => {
                            e.preventDefault();
                        });
                        setTimeout(() => liqpayFormContainer.querySelector('form').submit(), 1000);
                        
                    } catch (err) {
                        console.log(err);
                        this.alert("err", "Неможливо зробити замовлення без обраного товару", animDuration);
                    }
                }

                const { orderNumber } = await this.fetchData(path, methodType, submitedFormData);
                if (this.showSuccessModal && this.selectedBasketObj.selectedPayment !== "liqpay") {
                    this.showSuccessModal("Успіх! Замовлення прийнято",
                        `<p class="text-center">Супер, Ваше замовлення №${orderNumber} прийнято<br><br>Наш менеджер зв'яжеться із вами найближчим часом</p>`
                    );
                }
                this.hideHoleModals();
                this.hideModalLoader();
                if (clearCond) {
                    this.clearForm(this.initObj);
                    const selectors = document.querySelectorAll("select");
                    selectors.forEach((el) => el.value = null);
                    this.userAuthDefaultData();

                    if (this.productManager !== null) {
                        this.productManager.clearStorageProducts();
                        this.productManager.clearProducts();
                        this.basket.renderBasket();
                    }
                }


            } catch (err) {
                this.hideModalLoader();
                console.log(err);
                if (emptyForm) {
                    this.alert("err", "Будь ласка заповніть поля форми", animDuration);
                } else {
                    this.alert("err", err.message, animDuration);
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

    hideHoleModals(){
        document.querySelectorAll('.modal.show').forEach(modal => {
            this.bootstrap.Modal.getInstance(modal).hide();
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
