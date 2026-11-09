from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase


class GoogleSiteVerificationTests(SimpleTestCase):
    def test_verification_file_is_served_at_site_root(self):
        response = self.client.get("/googlefe45e590a621af8a.html")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.content,
            b"google-site-verification: googlefe45e590a621af8a.html",
        )


class SeoTemplateTests(SimpleTestCase):
    def render_base(self, path, url_name, product=None):
        request = RequestFactory().get(path)
        request.resolver_match = SimpleNamespace(url_name=url_name)
        return render_to_string(
            "products/base.html",
            {
                "request": request,
                "product": product,
                "full_url": path,
                "categories": [],
                "year": 2026,
            },
        )

    def test_category_meta_fields_are_used_when_meaningful(self):
        category = SimpleNamespace(
            name="Живопис",
            meta_title="Живопис",
            meta_description="Унікальний опис розділу живопису для художників.",
            image="",
        )
        html = render_to_string(
            "products/includes/category_seo.html",
            {"parent_category": category},
        )
        self.assertIn("Живопис — купити в Дніпрі | Артмагія", html)
        self.assertIn("Унікальний опис розділу живопису для художників.", html)
        self.assertNotIn("інтернет-магазині", html)

    def test_long_admin_title_replaces_generated_title(self):
        category = SimpleNamespace(
            name="Живопис",
            meta_title="Художні фарби та пензлі для живопису — Артмагія",
            meta_description="",
            image="",
        )
        html = render_to_string(
            "products/includes/category_seo.html",
            {"parent_category": category},
        )
        self.assertIn("Художні фарби та пензлі для живопису — Артмагія", html)

    def test_private_and_unconfirmed_pages_are_not_indexable(self):
        search = self.render_base("/product/search/", "sub_product")
        account = self.render_base("/user/profile/", "profile")
        hidden = self.render_base(
            "/product/detaile-product/1/",
            "detaile_product",
            product=SimpleNamespace(status=None),
        )
        visible = self.render_base(
            "/product/detaile-product/2/",
            "detaile_product",
            product=SimpleNamespace(status=True),
        )
        self.assertIn("noindex, nofollow", search)
        self.assertIn("noindex, nofollow", account)
        self.assertIn("noindex, follow", hidden)
        self.assertIn("index, follow", visible)

    def test_robots_opens_contacts_and_closes_service_areas(self):
        rules = open("robots.txt", encoding="utf-8").read()
        self.assertNotIn("Disallow: /main/contacts/", rules)
        self.assertNotIn("Disallow: /main/payment-delivery/", rules)
        self.assertIn("Disallow: /product/search/", rules)
        self.assertIn("Disallow: /main/safeguards/", rules)
        self.assertIn("Disallow: /user/", rules)
