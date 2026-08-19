# -*- coding: utf-8 -*-
"""Remise des classeurs Excel.

Le contrôleur ne contient AUCUNE logique métier : il vérifie les droits,
appelle la fabrique ``ev.export`` et renvoie le fichier. Tout ce qui décide
du contenu est dans les modèles, donc testable sans HTTP.
"""
from odoo import http
from odoo.http import content_disposition, request

_MIME_XLSX = ("application/vnd.openxmlformats-officedocument"
              ".spreadsheetml.sheet")


class EvExportController(http.Controller):

    def _remettre(self, nom, contenu):
        return request.make_response(contenu, headers=[
            ("Content-Type", _MIME_XLSX),
            ("Content-Length", len(contenu)),
            ("Content-Disposition", content_disposition(nom)),
        ])

    @http.route("/gestion_evaluation/fiche/<int:appraisal_id>.xlsx",
                type="http", auth="user")
    def fiche_evaluation(self, appraisal_id, **kw):
        appraisal = request.env["hr.appraisal"].browse(appraisal_id)
        # Les droits sont ceux d'Odoo : qui ne peut pas lire l'évaluation ne
        # peut pas en tirer la fiche.
        appraisal.check_access_rights("read")
        appraisal.check_access_rule("read")
        nom, contenu = request.env["ev.export"].fiche_evaluation(appraisal)
        return self._remettre(nom, contenu)

    @http.route("/gestion_evaluation/campagne/<int:campagne_id>.xlsx",
                type="http", auth="user")
    def recapitulatif_campagne(self, campagne_id, **kw):
        campagne = request.env["ev.campagne"].browse(campagne_id)
        campagne.check_access_rights("read")
        campagne.check_access_rule("read")
        nom, contenu = request.env["ev.export"].recapitulatif_campagne(campagne)
        return self._remettre(nom, contenu)
