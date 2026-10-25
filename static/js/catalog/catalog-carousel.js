// import { Swiper, Pagination, Navigation } from "../import.js";
import { PageProducts } from "../classes/page-products.js?v=4";
import { basket } from "../header/basket/basket.js?v=4";

const pageName = "catalog";

export const pageProductsCatalog = new PageProducts(pageName, "productsCatalogContainer",  `.main-${pageName}__carousel`, basket).initializePage();




