import {Swiper, Navigation, Pagination} from "../import.js";
import { PageProducts } from "../classes/page-products.js?v=4";
import { basket } from "../header/basket/basket.js?v=4";

const pageName = "index";

class IndexProducts extends PageProducts{
  constructor(pageName, containerId, swiper, basket){
    super(pageName, containerId, swiper, basket)
    this.basket.setPageName(pageName)
    this.swiperPagination = {...this.swiperPagination, productsPerPage: 12};
    this.initializePage();
  }

  async initializePage() {
    const { products, productsAmount, productsPerPage } = await this.fetchProducts(1);
    this.productsLists = this.renderProductsLists(productsAmount, productsPerPage);
    
    const mappedProducts = this.mapProducts(products);
    this.renderProductItemsOnList(mappedProducts, 1);

    this.renderPaginationBullets();
    this.setActivePaginationBullet(this.swiper.activeIndex);
    this.basket.setPageName(this.pageName);
    this.basket.initialize();
  }

  renderProductItem({ name, id, image, price }, container) {
    const productHTML = `
        <div class="products-${this.pageName}__item product-item" id="${id}">
            <div class="products-${this.pageName}__item__img__wrap">
                <img class="products-${this.pageName}__item__img" src="${image}" alt="${name}" />
            </div>
            <div class="products-index__item__content">
                <p class="products-${this.pageName}__item__title">${name}</p>
                <span class="products-${this.pageName}__item__price">${price} грн</span>
                <button class="btn btn-primary products-${this.pageName}__item__btn" data-item="product_btn">До кошика</button>
            </div>
        </div>
    `;
    container.insertAdjacentHTML('beforeend', productHTML);
  }

  async fetchProducts(page) {
    const { productsPerPage } = this.swiperPagination;
    const url = `${PROTOCOL}://${HOST}:${PORT}/get-new-arrivals/?page=${page}&productsPerPage=${productsPerPage}`;

    const response = await fetch(url, {
        method: "GET",
        mode: "cors",
        headers: {
          "Content-Type": "application/json"
        }
    });
    return await response.json();
  }

  setResponsiveProductsAmount() {
    const width = window.innerWidth;
    switch(true){
      case width >= 1400:
        this.defaultProductsAmount = 12;
        break;
      case width >= 1260:
        this.defaultProductsAmount = 12;
        break;
      case width >= 992:
        this.defaultProductsAmount = 12;
        break;
      case width >= 768:
        this.defaultProductsAmount = 12;
        break;
      case width >= 576:
        this.defaultProductsAmount = 12;
        break;
      case width >= 400:
        this.defaultProductsAmount = 12;
        break;
    }
  }
  
}

const { mainBanner } = {
 
  mainBanner: {
    autoplay: {
      delay: 4000,
      disableOnInteraction: false,
    },
    speed: 2000,
    loop: true,
    pagination: {
      el: ".swiper-pagination",
      dynamicBullets: true,
    },
  },
  modules: [Navigation, Pagination]
}

const mainBannerEl = document.querySelector(`.main-${pageName}__banner`);
if (mainBannerEl) new Swiper(mainBannerEl, mainBanner);

new IndexProducts(pageName, "productsIndexContainer", `.products-${pageName}__list__wrap`, basket)


