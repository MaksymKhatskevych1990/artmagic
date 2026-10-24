import { Swiper, Navigation, Pagination } from "../import.js";
import { PageProducts } from "../classes/page-products.js?v=3";
import { basket } from "../header/basket/basket.js?v=4";

const pageName = "category";

class CategoryProducts extends PageProducts {
  constructor(pageName, containerId, swiper, basket) {
    super(pageName, containerId, swiper, basket)
    this.basket.setPageName(pageName)
    this.initializePage();
  }

  async initializePage() {
    const { products, productsAmount, productsPerPage } = await this.fetchProducts(1);
    this.productsLists = this.renderProductsLists(productsAmount, productsPerPage);
    this.swiper.update();

    const mappedProducts = this.mapProducts(products);
    this.renderProductItemsOnList(mappedProducts, 1);

    this.renderGroup10Buttons();
    this.renderPaginationBullets();
    this.setActivePaginationBullet(this.swiper.activeIndex);
    this.updateSwiperHeight();

    this.basket.setPageName(this.pageName);
    this.basket.initialize();
  }

  async fetchProducts(page) {
    const pageUrl = window.location.href.split("/").filter(part => part !== "");
    const slug = pageUrl[pageUrl.length - 1];
    const { productsPerPage } = this.swiperPagination;
    const url = `${PROTOCOL}://${HOST}:${PORT}/category/${slug}/add-category?page=${page}&productsPerPage=${productsPerPage}`;

    const response = await fetch(url, {
      method: "GET",
      mode: "cors",
      headers: {
        "Accept": "application/json"
      }
    });
    return await response.json();
  }

  setResponsiveProductsAmount() {
    const width = window.innerWidth;
    switch(true){
      case width >= 1600:
        this.defaultProductsAmount = 12;
        break;
      case width >= 1400:
        this.defaultProductsAmount = 12;
        break;
      case width >= 1260:
        this.defaultProductsAmount = 9;
        break;
      case width >= 992:
        this.defaultProductsAmount = 6;
        break;
      case width >= 576:
        this.defaultProductsAmount = 4;
        break;
      case width >= 400:
        this.defaultProductsAmount = 2;
        break;
    }
  }

  
}

const categoryBanner = {
  autoplay: {
    delay: 4000,
    disableOnInteraction: false,
  },
  navigation: {
    nextEl: ".swiper-button-next",
    prevEl: ".swiper-button-prev",
  },
  speed: 2000,
  loop: true,
};

const brandsBanner = {
  autoplay: {
    delay: 4000,
  },
  direction: "vertical",
  pagination: {
    el: ".swiper-pagination",
    clickable: true,
  },
  speed: 2000,
  loop: true,
};



// Initialize Swiper instances
new Swiper(`.${pageName}-banner`, categoryBanner);
new Swiper(`.${pageName}-brands`, brandsBanner);
const categoryProducts = new CategoryProducts(pageName, "productsCategoryContainer", `.products-${pageName}__carousel`, basket);
