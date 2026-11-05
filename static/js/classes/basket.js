function notifyStock(text) {
    const label = document.querySelector("div#errorMessage");
    if (!label) {
        return;
    }
    const textNode = label.querySelector("div.alert-text");
    if (textNode) {
        textNode.textContent = text;
    }
    label.classList.add("alert_anim");
    setTimeout(() => label.classList.remove("alert_anim"), 5000);
}

export class Basket {
    constructor(productManager) {
        this.productManager = productManager;
        this.productsContainer = document.getElementById("basket-products");
        this.badge = document.querySelector(".header-basket__icon__badge");
        this.badgeContent = document.querySelector(".header-basket__icon__badge__number");
        this.tabCounts = document.querySelectorAll(".home-tabbar__count");
        this.allProductCostElement = document.querySelector(".modal-footer__text");
        this.images = document.querySelectorAll(".overlook__img");
        this.pageName = "index";
        this.liqpayIconContainer = document.querySelector("#liqpay").parentNode;
        window.onbeforeunload = () => {
            this.productManager.setStorageProducts(this.productManager.getProducts());
        };
        window.addEventListener("pageshow", () => {
            this.productManager.loadProductsFromStorage();
            this.renderBasket()
        })
        this.rerenderBasketCalled = false;
        this.handleBasketBtnsBuyInited = false;
        const basketModal = document.getElementById("basket__modal");
        if (basketModal) {
            basketModal.addEventListener("shown.bs.modal", () => {
                this.refreshStockFromServer();
            });
        }
    }

    async refreshStockFromServer() {
        if (!this.productManager.getProducts().length) {
            return;
        }
        try {
            const quote = await this.productManager.refreshStock();
            this.renderBasket();
            const checkoutButton = document.querySelector('button[data-submit="btn_Order"]');
            if (checkoutButton && checkoutButton.dataset.stockBlocked === "1") {
                checkoutButton.disabled = false;
                delete checkoutButton.dataset.stockBlocked;
            }
            if (quote.changed) {
                notifyStock("Ціна або наявність товарів у кошику змінилась. Перевірте кількість перед замовленням.");
            }
        } catch (error) {
            this.productManager.stockReady = false;
            const checkoutButton = document.querySelector('button[data-submit="btn_Order"]');
            if (checkoutButton) {
                checkoutButton.disabled = true;
                checkoutButton.dataset.stockBlocked = "1";
            }
            notifyStock(error.message || "Не вдалося перевірити наявність товарів. Спробуйте ще раз.");
        }
    }

    initialize() {
        this.initProductsBuyBtns();
        this.handleBasketBtnsBuyInited = true;
        this.renderBasket();
    }

    initProductsBuyBtns(page = 1){
        const productList = document.querySelectorAll(`.products-${this.pageName}__list`)[page - 1];
        // console.log(productList) 
        const btns = productList.querySelectorAll(`button[data-item="product_btn"]`);
        btns.forEach((btn) => {
            btn.addEventListener("click", async (e) => {
                const id = +e.target.closest(`div.product-item`).getAttribute("id");
                const product = await this.productManager.fetchNewProduct(id);
                await this.productManager.addProduct(product)
                this.renderBasket();
                this.animateBadge();
            });
        });
        this.addEventToDetailePage(productList);
    }

    addEventToDetailePage(productList){
        const products = productList.querySelectorAll(`div.product-item`);
        products.forEach(productElement => {
            productElement.addEventListener("click", (e) => {
                if(e.target.tagName === "BUTTON")
                    return 
                const currentEl = e.currentTarget;
                const currentElId = +currentEl.getAttribute("id");
                window.location.assign(`${PROTOCOL}://${HOST}:${PORT}/product/detaile-product/${currentElId}/`);
            })
        });
    }

    setPageName(pageName){
        this.pageName = pageName;
    }



    renderBasket() {
        if(this.productManager.products.length != 0)
            this.showOrHideLiqpayIcon();

        this.productsContainer.innerHTML = '';

        window.addEventListener("DOMContentLoaded", () => {
            this.productManager.setProducts(this.productManager.getStorageProducts());
        })

        const products = this.productManager.getProducts();
        
        if (products.length === 0) 
            this.productsContainer.innerHTML = '<p class="basket__empty">Кошик порожній</p>';
        else {
            products.forEach((product) => {
                const productHTML = this.renderProduct(product);
                this.productsContainer.appendChild(productHTML);
            });
        }

        // Обновление бейджа корзины

        this.updateCounts();

        // Обновление общей стоимости товаров
        this.allProductCostElement.textContent = `${this.productManager.allProductsTotalPrice(this.productManager.priceOutputFn, 2)} грн`;
        this.images = document.querySelectorAll(".overlook__img");
        rerenderImage(this.images);


    }

    renderProduct(product) {
        const productDiv = document.createElement("div");
        productDiv.classList.add("cart__product");
        productDiv.setAttribute("id", `cart__product__${product.id}`);
    
        // Определяем доступное количество и количество для предзаказа
        // console.log(product.quantity, product.storageQuantity)
        const availableQuantity = Math.min(product.quantity, product.storageQuantity);
        // console.log(product)
        product.quantity = availableQuantity;
        const preorderQuantity = product.quantity >= product.storageQuantity;
        // Проверяем, нужно ли отображать две пары кнопок
        const showPreorder = preorderQuantity;
    
        let productBtns = `
            <div class="cart__product__btns__wrap-container">
                <div class="cart__product__btns__wrap">
                    <p class="text-bold text-center с17">В наявності</p>
                    <div class="cart__product__btns">
                        <button class="btns__btn" data-id="${product.id}" data-action="decrease">-</button>
                        <input class="btns__count" data-action="quantity" type="text" value="${availableQuantity}" />
                        <button class="btns__btn" data-id="${product.id}" data-action="increase">+</button>
                    </div>
                `;
    
        if (showPreorder) {
            productBtns += `
                <p class="c11 text-bold text-center">Замовити</p>
                <div class="cart__product__btns">
                    <button class="btns__btn" data-id="${product.id}" data-action="decrease-preorder">-</button>
                    <input class="btns__count с11" data-action="quantity-preorder" type="text" value="${product.preorder}" />
                    <button class="btns__btn" data-id="${product.id}" data-action="increase-preorder">+</button>
                </div>`;
        }
    
        productBtns += `</div></div>`;
    
        productDiv.innerHTML = `
            <div class="cart__product__overlook">
                <div class="overlook__img__container">
                    <div class="overlook__img__wrap">
                        <img class="overlook__img" src="${product.image}" alt="${product.name}" />
                    </div>
                </div>
                <div class="overlook__name__wrap">
                    <p class="overlook__name">${product.name}</p>
                    <p class="overlook__name">Артикул: <b class="c17">${product.model}</b></p>
                    <p class="overlook__name">Ціна: <b>${product.price}  грн</b></p>
                </div>
                ${productBtns}
                <div class="cart__product__price">
                    ${this.productManager.priceOutputFn(product.price * product.quantity, 2)} грн
                </div>
                <button class="cart__product__garbage__wrap" data-id="${product.id}" data-action="remove">
                    <svg class="cart__product__garbage" viewBox="0 0 448 512" fill="currentColor">
                        <path d="M135.2 17.7C140.6 6.8 151.7 0 163.8 0H284.2c12.1 0 23.2 6.8 28.6 17.7L320
                            32h96c17.7 0 32 14.3 32 32s-14.3 32-32 32H32C14.3 96 0 81.7 0 64S14.3 32 32 32h96l7.2-14.3zM32
                            128H416V448c0 35.3-28.7 64-64 64H96c-35.3 0-64-28.7-64-64V128zm96 64c-8.8 0-16 7.2-16 16V432c0
                            8.8 7.2 16 16 16s16-7.2 16-16V208c0-8.8-7.2-16-16-16zm96 0c-8.8 0-16 7.2-16 16V432c0 8.8 7.2 16
                            16 16s16-7.2 16-16V208c0-8.8-7.2-16-16-16zm96 0c-8.8 0-16 7.2-16 16V432c0 8.8 7.2 16 16 16s16-7.2
                            16-16V208c0-8.8-7.2-16-16-16z">
                        </path>
                    </svg>
                </button>
            </div>
        `;
    
        // Обработчики событий для управления количеством товара и предзаказа
        this.setupProductEventListeners(product, productDiv, showPreorder);
    
        return productDiv;
    }
    
    // Метод для настройки обработчиков событий
    setupProductEventListeners(product, productDiv, showPreorder) {
        // Обработчик увеличения количества
        productDiv.querySelector(`[data-action="increase"]`).addEventListener("click", () => {
            product.addOne();
            this.renderBasket(); // Обновляем корзину
        });
    
        // Обработчик уменьшения количества
        productDiv.querySelector(`[data-action="decrease"]`).addEventListener("click", () => {
            product.removeOne();
            this.renderBasket(); // Обновляем корзину
        });
    
        // Обработчик удаления продукта
        productDiv.querySelector(`[data-action="remove"]`).addEventListener("click", () => {
            this.productManager.deleteProduct(product.id);
            this.renderBasket(); // Обновляем корзину
        });
    
        // Обработчики для предзаказа, если нужно
        if (showPreorder) {
            productDiv.querySelector(`[data-action="increase-preorder"]`).addEventListener("click", () => {
                product.preorder += 1; // Увеличиваем количество предзаказа
                this.renderBasket();
            });
    
            productDiv.querySelector(`[data-action="decrease-preorder"]`).addEventListener("click", () => {
                if (product.preorder > 0) {
                    product.preorder -= 1; // Уменьшаем количество предзаказа, если больше нуля
                    this.renderBasket();
                }
            });
        }
    }
    
    
    

    

    updateProductQuantityAndPrice(productId, quantityInput, totalPriceElement) {
        const product = this.productManager.existProduct(productId);
        if (product) {
            quantityInput.value = product.quantity;
            totalPriceElement.textContent = `${this.productManager.priceOutputFn(product.price * product.quantity, 2)} грн`;
            this.updateTotalPrice();
        }
    }

    updateTotalPrice() {
        this.allProductCostElement.textContent = `${this.productManager.allProductsTotalPrice(this.productManager.priceOutputFn, 2)} грн`;
    }

    updateCounts() {
        const count = this.productManager.productsTotalCount();
        if (this.badgeContent) this.badgeContent.textContent = count;
        this.tabCounts.forEach((el) => {
            el.textContent = count;
            el.classList.toggle("is-on", count > 0);
        });
    }

    animateBadge() {
        if (this.badge) {
            this.badge.classList.add("animated");
            this.badge.addEventListener("animationend", () => {
                this.badge.classList.remove("animated");
            }, { once: true });
        }
        this.tabCounts.forEach((el) => {
            el.classList.remove("is-bump");
            void el.offsetWidth;
            el.classList.add("is-bump");
        });
    }

    showOrHideLiqpayIcon(){
        if (this.productManager.isOrderedStoreProduct()) {
            this.liqpayIconContainer.classList.remove("d-none");
            this.liqpayIconContainer.classList.add("d-block");
        } else {
            this.liqpayIconContainer.classList.remove("d-block");
            this.liqpayIconContainer.classList.add("d-none");
        }
    }
    

    
}