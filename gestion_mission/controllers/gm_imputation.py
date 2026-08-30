# -*- coding: utf-8 -*-
"""Téléchargement de la fiche d'imputation comptable (Excel).

Route backend : l'accès passe par les droits ORM habituels (la lecture
de la mission est refusée si l'utilisateur n'y a pas droit) et le
document est réservé aux gestionnaires — c'est une pièce comptable.
"""
from odoo import http, _
from odoo.http import request
from odoo.exceptions import AccessError


class GmImputationController(http.Controller):

    @http.route("/gm/mission/<int:mission_id>/imputation.xlsx",
                type="http", auth="user")
    def imputation_xlsx(self, mission_id, **kw):
        if not request.env.user.has_group(
                "gestion_mission.group_gm_manager"):
            raise AccessError(_(
                "La fiche d'imputation comptable est réservée aux "
                "gestionnaires des missions."))
        mission = request.env["gm.mission"].browse(mission_id)
        mission.check_access_rights("read")
        mission.check_access_rule("read")
        contenu = mission._build_imputation_xlsx()
        nom = "Fiche imputation %s.xlsx" % (
            (mission.name or "mission").replace("/", "-"))
        return request.make_response(contenu, headers=[
            ("Content-Type", "application/vnd.openxmlformats-officedocument"
                             ".spreadsheetml.sheet"),
            ("Content-Length", len(contenu)),
            ("Content-Disposition", 'attachment; filename="%s"' % nom),
            ("X-Content-Type-Options", "nosniff"),
        ])
