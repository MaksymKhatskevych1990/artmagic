import { productManager, basket } from "./basket.js?v=5";
import "../../../node_modules/bootstrap/dist/js/bootstrap.bundle.js";
import { basketModalCarousel } from "../header.js?v=2";
const { MIN_2_LETTERS_UA, FIRST_LETTER_CAPITALISE_UA, EMAIL, PHONE_UA, REQUIRED, POSTAL_INDEX }  = regexp;

const formDataOrder = {
    fullName: "",
    clientPhone: "",
    email: "",
    city: "",
    address: "",
    area: "",
    department: "",
}

// Не забувати, що патерни можуть перекривати один одного
const patternsOrder = {
    fullName: [
        { rule:  MIN_2_LETTERS_UA, errorMsg: "Мінімум 2 літери UA"},
    ],
    email: [
        { rule: EMAIL, errorMsg: "Неправильний email" }
    ],
    clientPhone: [
        { rule: PHONE_UA, errorMsg: "Неправильний номер телефону" }
    ],
    address: [
        { rule:  MIN_2_LETTERS_UA, errorMsg: "Мінімум 2 літери UA"},
    ],
    city: [],
};

basket.renderBasket();

const userData = new Map();

Array.from(document.querySelectorAll("[data-user]")).map(el => {
    const key = el.dataset.user;
    const val = el.textContent;
    userData.set(key, val)
    return userData
});


export const formOrder = new Form(formDataOrder, patternsOrder, "Order", Alert,  productManager, basket, userData, bootstrap, basketModalCarousel);

formOrder.initForm("orderForm", {
    fullName: "name",
    email: "email",
    clientPhone: "phone",
    city: "city",
    address: "address",
    area: "area",
    products: "products",
    department: "department",
}, "cart/checkout/", "POST",
    {successMessage: "Ваше замовлення успішно прийняте", errorMessage: "Якась помилка"},
    3000, true
);

