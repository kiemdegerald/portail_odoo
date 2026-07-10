# -*- coding: utf-8 -*-
"""Portail validateur — congés de mon équipe (/my/team/leaves) :
consultation des demandes des employés dont on est « Validateur congés »,
et décision (approuver/refuser) avec commentaire obligatoire."""
from odoo import http, SUPERUSER_ID, _
from odoo.http import request
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from odoo.addons.portal.controllers.portal import pager as portal_pager

from .portal_common import (
    PortailCommon,
    LEAVE_STATE_LABELS,
    LEAVE_APPROVABLE_STATES,
)

# Messages de confirmation affichés après une action sur /my/team/leaves
TEAM_LEAVE_SUCCESS_MESSAGES = {
    "approved": "La demande de congé a été approuvée.",
    "refused": "La demande de congé a été refusée.",
}

# Décisions possibles d'un validateur sur une demande de son périmètre
TEAM_LEAVE_DECISIONS = {
    "approve": {"method": "action_approve", "success": "approved",
                "label": "Demande approuvée"},
    "refuse": {"method": "action_refuse", "success": "refused",
               "label": "Demande refusée"},
}


class PortailValidateur(PortailCommon):

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_team_leave_or_redirect(self, leave_id, require_pending=True):
        """Retourne la demande si elle appartient à un employé dont
        l'utilisateur connecté est le validateur, sinon lève.
        ``require_pending`` impose en plus qu'elle soit encore en attente
        (pour statuer) ; la consultation (bouton « Voir ») reste possible
        quel que soit l'état."""
        managed = self._get_managed_employees()
        leave = request.env["hr.leave"].sudo().browse(leave_id).exists()
        if not leave:
            raise MissingError(_("Cette demande de congé n'existe pas."))
        if leave.employee_id not in managed:
            raise AccessError(_("Vous n'avez pas accès à cette demande de congé."))
        if require_pending and leave.state not in LEAVE_APPROVABLE_STATES:
            raise AccessError(_("Cette demande a déjà été traitée."))
        return leave

    def _team_leave_detail_values(self, leave, error=None, comment=""):
        """Valeurs communes du rendu de la page de détail d'une demande."""
        return {
            "leave": leave,
            "leave_state_labels": LEAVE_STATE_LABELS,
            "leave_approvable_states": LEAVE_APPROVABLE_STATES,
            "attachments": self._get_leave_attachments(leave),
            "decision_error": error,
            "decision_comment": comment,
            "page_name": "team_leave",
        }

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------
    @http.route(["/my/team/leaves", "/my/team/leaves/page/<int:page>"],
                type="http", auth="user", website=True)
    def portal_team_leaves(self, page=1, filterby=None, **kw):
        managed = self._get_managed_employees()
        if not managed:
            return request.redirect("/my")

        Leave = request.env["hr.leave"].sudo()
        searchbar_filters = {
            "pending": {"label": _("À approuver"),
                        "domain": [("state", "in", list(LEAVE_APPROVABLE_STATES))]},
            "all": {"label": _("Toutes"), "domain": []},
        }
        if filterby not in searchbar_filters:
            filterby = "pending"
        domain = [("employee_id", "in", managed.ids)] + searchbar_filters[filterby]["domain"]

        leave_count = Leave.search_count(domain)
        pager = portal_pager(
            url="/my/team/leaves",
            url_args={"filterby": filterby},
            total=leave_count,
            page=page,
            step=self._items_per_page,
        )
        leaves = Leave.search(
            domain, order="date_from desc", limit=self._items_per_page, offset=pager["offset"]
        )

        values = {
            "leaves": leaves,
            "leave_state_labels": LEAVE_STATE_LABELS,
            "leave_approvable_states": LEAVE_APPROVABLE_STATES,
            "success_message": TEAM_LEAVE_SUCCESS_MESSAGES.get(kw.get("success")),
            "error_message": kw.get("error"),
            "page_name": "team_leave",
            "pager": pager,
            "default_url": "/my/team/leaves",
            "searchbar_filters": searchbar_filters,
            "filterby": filterby,
        }
        return request.render("portail.portal_team_leaves", values)

    @http.route(["/my/team/leaves/<int:leave_id>/attachment/<int:attachment_id>"],
                type="http", auth="user", website=True)
    def portal_team_leave_attachment(self, leave_id=None, attachment_id=None, **kw):
        """Justificatif vu par le validateur (demande de son périmètre,
        quel que soit son état). ``?inline=1`` : aperçu dans le navigateur."""
        try:
            leave = self._get_team_leave_or_redirect(leave_id, require_pending=False)
            return self._serve_leave_attachment(
                leave, attachment_id, inline=kw.get("inline") == "1")
        except (AccessError, MissingError):
            return request.redirect("/my/team/leaves")

    @http.route(["/my/team/leaves/<int:leave_id>"],
                type="http", auth="user", website=True)
    def portal_team_leave_detail(self, leave_id=None, **kw):
        """Bouton « Voir » : détail d'une demande du périmètre.

        Consultable quel que soit l'état ; le bloc « Statuer » n'apparaît que
        si la demande est encore en attente.
        """
        try:
            leave = self._get_team_leave_or_redirect(leave_id, require_pending=False)
        except (AccessError, MissingError):
            return request.redirect("/my/team/leaves")
        return request.render("portail.portal_team_leave_detail",
                              self._team_leave_detail_values(leave))

    @http.route(["/my/team/leaves/<int:leave_id>/decide"],
                type="http", auth="user", website=True, methods=["POST"])
    def portal_team_leave_decide(self, leave_id=None, decision=None, comment=None, **post):
        """Approuve ou refuse une demande, avec commentaire OBLIGATOIRE.

        L'action métier est exécutée en tant que SUPERUSER : la validation
        Odoo crée notamment une réunion calendrier ``with_user(uid courant)``,
        ce qui échouerait avec un utilisateur portail (sans droits internes).
        Le contrôle d'accès métier (la demande appartient bien au périmètre
        du validateur connecté) est fait AVANT, par
        ``_get_team_leave_or_redirect``.
        """
        try:
            leave = self._get_team_leave_or_redirect(leave_id)
        except (AccessError, MissingError):
            return request.redirect("/my/team/leaves")

        spec = TEAM_LEAVE_DECISIONS.get(decision)
        if not spec:
            return request.redirect("/my/team/leaves")
        comment = (comment or "").strip()
        if not comment:
            # Champ requis côté navigateur, mais on revérifie côté serveur.
            return request.render(
                "portail.portal_team_leave_detail",
                self._team_leave_detail_values(
                    leave,
                    error=_("Veuillez saisir un commentaire (la raison de votre "
                            "décision) avant de statuer."),
                ))

        leave_su = leave.with_user(SUPERUSER_ID)
        try:
            getattr(leave_su, spec["method"])()
        except (UserError, ValidationError) as exc:
            msg = exc.args[0] if exc.args else str(exc)
            return request.render(
                "portail.portal_team_leave_detail",
                self._team_leave_detail_values(leave, error=msg, comment=comment))

        # Enregistre le validateur comme approbateur (l'action étant faite par
        # OdooBot, le champ standard resterait vide sinon).
        manager_employee = self._get_portal_employees()[:1]
        if spec["success"] == "approved" and manager_employee and not leave_su.first_approver_id:
            leave_su.write({"first_approver_id": manager_employee.id})
        # Raison visible par l'employé (portail) et les RH (fiche + chatter)
        leave_su.write({"portail_decision_note": comment})
        leave_su.message_post(
            body=_("%(label)s depuis le portail par %(user)s. Raison : %(reason)s",
                   label=_(spec["label"]), user=request.env.user.name,
                   reason=comment),
            author_id=request.env.user.partner_id.id,
            message_type="comment",
        )
        # Prévient l'employé de la décision (jamais bloquant).
        leave_su._portail_notify_employee_decision()
        return request.redirect("/my/team/leaves?success=%s" % spec["success"])
