import { Basket } from "../../classes/basket.js?v=5";
import { ProductManager } from "../../classes/product-manager.js?v=5";

export const productManager = new ProductManager();
export const basket = new Basket(productManager);



