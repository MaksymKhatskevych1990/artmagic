import { basket, productManager } from "../header/basket/basket.js?v=5";

const btn = document.querySelector(".product-details__btn__add-to-cart")

btn.addEventListener("click", async (e) => {
    const id = +e.target.getAttribute("id");
    const product = await productManager.fetchNewProduct(id);
    await productManager.addProduct(product);
    basket.renderBasket();
    basket.animateBadge();
});

