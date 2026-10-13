"""Sitemaps para indexación en buscadores."""
from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Category, Product


class ProductSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return Product.objects.active().order_by('-updated_at')

    def lastmod(self, obj):
        return obj.updated_at


class CategorySitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.6

    def items(self):
        return Category.objects.active()

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return obj.get_absolute_url()


class StaticViewSitemap(Sitemap):
    changefreq = 'monthly'
    priority = 0.5

    #: La portada pesa más que el resto de páginas estáticas.
    PRIORITIES = {'store:home': 1.0, 'store:product_list': 0.9}

    def items(self):
        return [
            'store:home',
            'store:product_list',
            'store:offers',
            'store:about',
            'store:contact',
            'store:shipping',
            'store:terms',
            'store:privacy',
        ]

    def priority(self, item):
        return self.PRIORITIES.get(item, 0.5)

    def location(self, item):
        return reverse(item)
