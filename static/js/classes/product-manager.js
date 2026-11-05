export class ProductManager {
    constructor() {
        this.products = [];
        this.stockReady = false;
        this.lastFingerprint = null;
        this.lastQuote = null;
        this.stockConfirmationRequired = false;
        this.unconfirmedQuote = null;
        this.loadProductsFromStorage();
    }

    getProducts() {
        return this.products ?? [];
    }

    getStorageProducts() {
        const products = JSON.parse(localStorage.getItem("products"));
        return this.mapObjectsInProducts(products) ?? [];
    }

    setProducts(products) {
        this.products = products;
    }

    setStorageProducts(products) {
        localStorage.setItem("products", JSON.stringify(products));
    }

    deleteProduct(id) {
        this.products = this.products.filter((product) => product.id !== id);
        this.setStorageProducts(this.products)
    }

    clearProducts() {
        this.products = [];
    }

    clearStorageProducts() {
        localStorage.setItem('products', JSON.stringify([]));
    }

    async addProduct({ id, name, price, image, model, storageQuantity}) {
        
        const existProduct = this.existProduct(id);
        if (existProduct)
            existProduct.addOne();
        else {
            let preorder = 0;
            if(storageQuantity == 0)
                preorder = 1;
            const newProduct = new Product(id, name, price, image, model, null, preorder, storageQuantity);
            this.products = [...this.products, newProduct];
        }
        this.setStorageProducts(this.products)
        // console.log(this.isOrderedStoreProduct(), "isOrderedStoreProduct");
    }

    mapObjectsInProducts(products) {
        if (!products) return [];
        return products.map(({ id, name, price, quantity, image, model, preorder, storageQuantity }) =>
            new Product(id, name, price, image, model, quantity, preorder, storageQuantity)
        );
    }

    mapObjectInProduct({id, name, price, image, model, quantity, preorder, storageQuantity}) {
        if (!id) return null;
        return new Product(id, name, price, image, model, quantity, preorder, storageQuantity);
    }

    async fetchNewProduct(id) {
        const response = await fetch(`${PROTOCOL}://${HOST}:${PORT}/add-to-cart/?id=${id}`, {
            method: "GET",
            mode: "cors"
        });
        const product = await response.json();
        return product;
    }

    existProduct(id) {
        return this.products.find((product) => product.id === id) ?? null;
    }

    productsTotalCount() {
        return this.products.reduce((acc, cur) => acc + (Number(cur.quantity) || 0) + (Number(cur.preorder) || 0), 0);
    }

    currentProductTotalPrice(id, priceOutputFn, amountAfterQuote) {
        const curProduct = this.products.find((product) => product.id === id);
        return priceOutputFn(curProduct.quantity * curProduct.price, amountAfterQuote);
    }

    allProductsTotalPrice(priceOutputFn, amountAfterQuote) {
        return priceOutputFn(
            this.products.reduce((acc, cur) => acc + +this.currentProductTotalPrice(cur.id, priceOutputFn, amountAfterQuote), 0),
            amountAfterQuote
        );
    }

    priceOutputFn(number, amountAfterQuote) {
        return number.toFixed(amountAfterQuote);
    }

    setProductQuantity(id, value) {
        const curProduct = this.existProduct(id);
        curProduct.setQuantity(value);
    }

    loadProductsFromStorage() {
        this.setProducts(this.getStorageProducts());
    }

    
    filterProductsByQuantity(products) {
        return products.filter(product => product.quantity > 0 || product.preorder > 0);
    }

    getProductsInfo() {
        return this.products.map(({id, name, price, quantity}, i) => 
            `${i + 1}) Продукт 
             Назва: ${name}
             Ціна: ${price} грн
             Кільіксть: ${quantity}
             Ціна загальна: ${this.currentProductTotalPrice(id, this.priceOutputFn, 2)} грн`
        ).join('\n');
    }

    isOrderedStoreProduct(){
        return this.products.some(product => product.quantity > 0);
    }

    async refreshStock() {
        const products = this.getProducts();
        if (!products.length) {
            this.stockReady = true;
            this.lastFingerprint = null;
            this.lastQuote = { status: "success", changed: false, items: [], total: "0.00", preorder_total: "0.00", fingerprint: "" };
            return this.lastQuote;
        }
        let response;
        try {
            response = await fetch(`${PROTOCOL}://${HOST}:${PORT}/cart/refresh/`, {
                method: "POST",
                mode: "cors",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": readCookie("csrftoken"),
                },
                body: JSON.stringify({
                    items: products.map((product) => ({
                        id: product.id,
                        quantity: Number(product.quantity) || 0,
                        preorder: Number(product.preorder) || 0,
                        price: product.price,
                    })),
                }),
            });
        } catch (error) {
            this.stockReady = false;
            throw new Error("Не вдалося перевірити наявність товарів. Спробуйте ще раз.");
        }
        let data = null;
        try {
            data = await response.json();
        } catch (error) {
            this.stockReady = false;
            throw new Error("Не вдалося перевірити наявність товарів. Спробуйте ще раз.");
        }
        if (!response.ok || data.status === "error") {
            this.stockReady = false;
            throw new Error(data && data.message ? data.message : "Не вдалося перевірити наявність товарів. Спробуйте ще раз.");
        }
        this.applyRefresh(data);
        this.stockReady = true;
        this.lastFingerprint = data.fingerprint;
        this.lastQuote = data;
        if (data.changed) {
            this.stockConfirmationRequired = true;
            this.unconfirmedQuote = data;
        }
        return data;
    }

    confirmStockQuote() {
        this.stockConfirmationRequired = false;
        this.unconfirmedQuote = null;
    }

    applyRefresh(data) {
        const items = new Map((data.items || []).map((item) => [Number(item.id), item]));
        const next = [];
        this.products.forEach((product) => {
            const item = items.get(Number(product.id));
            if (!item || item.unavailable) {
                return;
            }
            product.name = item.name || product.name;
            product.model = item.model || product.model;
            product.price = Number(item.unit_price);
            product.storageQuantity = Number(item.available) || 0;
            product.quantity = Number(item.quantity) || 0;
            product.preorder = Number(item.preorder) || 0;
            product.isQuantityDisabled = product.quantity > product.storageQuantity;
            next.push(product);
        });
        this.products = next;
        this.setStorageProducts(this.products);
    }
    
}

function readCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== "") {
        const cookies = document.cookie.split(";");
        for (let cookie of cookies) {
            cookie = cookie.trim();
            if (cookie.startsWith(name + "=")) {
                cookieValue = decodeURIComponent(cookie.slice(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}
