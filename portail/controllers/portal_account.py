# -*- coding: utf-8 -*-
"""Portail employé — « Modifier mes informations » (/my/account).

Le template associé (portal_templates_account.xml) retire les champs
société/TVA et grise nom + e-mail ; ce contrôleur applique le même verrou
CÔTÉ SERVEUR (défense contre les requêtes forgées).
"""
from odoo import http
from odoo.http import request

from .portal_common import PortailCommon


class PortailCompte(PortailCommon):

    @http.route()
    def account(self, redirect=None, **post):
        """Pour un employé, le nom et l'e-mail sont gérés par les RH : les
        champs sont en lecture seule dans le template, et on neutralise ici
        toute valeur soumise malgré tout (requête forgée). Société/TVA sont
        retirés du formulaire — on les ignore de même côté serveur.
        """
        if (request.httprequest.method == "POST" and post
                and self._get_portal_employees()):
            partner = request.env.user.partner_id
            post["name"] = partner.name or ""
            post["email"] = partner.email or ""
            post.pop("company_name", None)
            post.pop("vat", None)
        return super().account(redirect=redirect, **post)

    @http.route()
    def deactivate_account(self, validation=None, password=None, **post):
        """La suppression de son propre compte est INTERDITE aux employés :
        leurs comptes sont gérés par les RH. Le bloc est déjà retiré de la
        page « Connexion & Sécurité » (portal_templates_account.xml) — on
        neutralise aussi la route pour parer une requête forgée.
        """
        if self._get_portal_employees():
            return request.redirect("/my/security")
        return super().deactivate_account(
            validation=validation, password=password, **post)
