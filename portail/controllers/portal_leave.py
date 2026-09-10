# -*- coding: utf-8 -*-
"""Portail employé — mes congés (/my/leaves) : solde, historique,
modification/annulation d'une demande en attente, justificatifs."""
from datetime import date, datetime

from odoo import http, _
from odoo.http import request
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from odoo.addons.portal.controllers.portal import pager as portal_pager

from .portal_common import (
    PortailCommon,
    LEAVE_STATE_LABELS,
    LEAVE_EDITABLE_STATES,
)

# Messages de confirmation affichés après une action sur /my/leaves
LEAVE_SUCCESS_MESSAGES = {
    "edited": "Votre demande de congé a été modifiée.",
    "cancelled": "Votre demande de congé a été annulée.",
}


class PortailConges(PortailCommon):

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_leave_or_redirect(self, leave_id, require_editable=False):
        """Retourne la demande si elle appartient à l'employé courant, sinon lève.

        ``require_editable`` impose en plus que la demande soit encore modifiable
        (pas encore approuvée ni refusée).
        """
        employees = self._get_portal_employees()
        leave = request.env["hr.leave"].sudo().browse(leave_id).exists()
        if not leave:
            raise MissingError(_("Cette demande de congé n'existe pas."))
        if leave.employee_id not in employees:
            raise AccessError(_("Vous n'avez pas accès à cette demande de congé."))
        if require_editable and leave.state not in LEAVE_EDITABLE_STATES:
            raise AccessError(_(
                "Cette demande a déjà été traitée et ne peut plus être modifiée."
            ))
        return leave

    def _get_portal_leave_types(self, current_type=None):
        """Types de congé proposés à l'employé sur le portail (édition).

        Alignés sur le formulaire de création : les types cochés « Proposé
        sur le portail » (``portail_published``, configurable par les RH sans
        redéploiement). Le type actuel de la demande est toujours inclus,
        afin qu'une demande créée avec un autre type reste éditable sans
        perdre son type d'origine.
        """
        types = request.env["hr.leave.type"].sudo().search(
            [("portail_published", "=", True)], order="id")
        if current_type and current_type not in types:
            types = current_type | types
        return types

    def _leave_form_defaults(self, leave):
        """Valeurs de pré-remplissage du formulaire à partir de la demande.

        Le motif est lu dans ``private_name`` (champ réel) : le champ ``name``
        est calculé avec masquage de confidentialité et renverrait ``*****``
        pour un utilisateur portail, même sur sa propre demande.
        """
        return {
            "holiday_status_id": str(leave.holiday_status_id.id) if leave.holiday_status_id else "",
            "request_date_from": leave.request_date_from.strftime("%Y-%m-%d") if leave.request_date_from else "",
            "request_date_to": leave.request_date_to.strftime("%Y-%m-%d") if leave.request_date_to else "",
            "name": leave.private_name or "",
        }

    def _validate_leave_form(self, post, leave_types):
        """Valide les champs soumis. Retourne un dict {champ: message} (vide si OK)."""
        error = {}

        type_id = (post.get("holiday_status_id") or "").strip()
        if not type_id.isdigit() or int(type_id) not in leave_types.ids:
            error["holiday_status_id"] = _("Veuillez choisir un type de congé valide.")

        date_from = (post.get("request_date_from") or "").strip()
        date_to = (post.get("request_date_to") or "").strip()
        d_from = d_to = None

        if not date_from:
            error["request_date_from"] = _("La date de début est obligatoire.")
        else:
            try:
                d_from = datetime.strptime(date_from, "%Y-%m-%d").date()
            except ValueError:
                error["request_date_from"] = _("Date de début invalide.")

        if not date_to:
            error["request_date_to"] = _("La date de fin est obligatoire.")
        else:
            try:
                d_to = datetime.strptime(date_to, "%Y-%m-%d").date()
            except ValueError:
                error["request_date_to"] = _("Date de fin invalide.")

        if d_from and d_to and d_to < d_from:
            error["request_date_to"] = _(
                "La date de fin ne peut pas précéder la date de début."
            )

        # Dates passées : refusées, sauf pour les types explicitement
        # autorisés (ex. Congé maladie, régularisé après coup).
        if d_from and not error.get("holiday_status_id") and d_from < date.today():
            leave_type = leave_types.filtered(lambda t: t.id == int(type_id))
            if not leave_type.portail_allow_past_dates:
                error["request_date_from"] = _(
                    "Les dates passées ne sont pas autorisées pour ce type "
                    "de congé.")

        return error

    def _get_leave_balances(self, employees):
        """Solde par type de congé pour l'employé courant.

        Renvoie une liste de dicts prêts pour le template.
        """
        balances = []
        if not employees:
            return balances
        LeaveType = request.env["hr.leave.type"].sudo()
        for employee in employees:
            company = employee.company_id
            leave_types = LeaveType.with_context(
                allowed_company_ids=company.ids or request.env.company.ids
            ).search([("company_id", "in", [False] + company.ids)], order="id")
            try:
                data = leave_types.get_allocation_data(employee)[employee]
            except Exception:
                data = []
            for name, info, _requires, _lt_id in data:
                balances.append({
                    "employee": employee.name,
                    "name": name,
                    "allocated": info.get("max_leaves", 0),
                    "taken": info.get("leaves_taken", 0),
                    "remaining": info.get("virtual_remaining_leaves", 0),
                    "unit": info.get("request_unit", "day"),
                })
        return balances

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------
    @http.route(["/my/leaves", "/my/leaves/page/<int:page>"],
                type="http", auth="user", website=True)
    def portal_my_leaves(self, page=1, **kw):
        employees = self._get_portal_employees()
        Leave = request.env["hr.leave"].sudo()
        domain = [("employee_id", "in", employees.ids)]

        leave_count = Leave.search_count(domain)
        pager = portal_pager(
            url="/my/leaves",
            total=leave_count,
            page=page,
            step=self._items_per_page,
        )
        leaves = Leave.search(
            domain, order="date_from desc", limit=self._items_per_page, offset=pager["offset"]
        )

        values = {
            "leaves": leaves,
            "balances": self._get_leave_balances(employees),
            "leave_state_labels": LEAVE_STATE_LABELS,
            "leave_editable_states": LEAVE_EDITABLE_STATES,
            "success_message": LEAVE_SUCCESS_MESSAGES.get(kw.get("success")),
            "portail_is_manager": bool(self._get_managed_employees()),
            "page_name": "leave",
            "pager": pager,
            "default_url": "/my/leaves",
        }
        return request.render("portail.portal_my_leaves", values)

    @http.route(["/my/leaves/<int:leave_id>/edit"],
                type="http", auth="user", website=True, methods=["GET", "POST"])
    def portal_my_leave_edit(self, leave_id=None, **post):
        try:
            leave = self._get_leave_or_redirect(leave_id, require_editable=True)
        except (AccessError, MissingError):
            return request.redirect("/my/leaves")

        leave_types = self._get_portal_leave_types(current_type=leave.holiday_status_id)
        error = {}

        if request.httprequest.method == "POST":
            error = self._validate_leave_form(post, leave_types)
            if not error:
                vals = {
                    "holiday_status_id": int(post["holiday_status_id"]),
                    "request_date_from": post["request_date_from"],
                    "request_date_to": post["request_date_to"],
                    # champ réel du motif (cf. _leave_form_defaults)
                    "private_name": post.get("name") or False,
                }
                try:
                    with self._ecriture_atomique():
                        leave.sudo().write(vals)
                        # Justificatif(s) ajouté(s) à l'édition (facultatif).
                        # Lus depuis la requête HTTP : avec un input `multiple`,
                        # request.params ne conserve qu'un seul fichier par nom.
                        for file_storage in request.httprequest.files.getlist("justificatif"):
                            self._attach_leave_file(leave, file_storage)
                        return request.redirect("/my/leaves?success=edited")
                except (UserError, ValidationError) as exc:
                    error["global"] = exc.args[0] if exc.args else str(exc)

        form_values = post if request.httprequest.method == "POST" \
            else self._leave_form_defaults(leave)

        values = {
            "leave": leave,
            "leave_types": leave_types,
            "leave_state_labels": LEAVE_STATE_LABELS,
            "error": error,
            "form_values": form_values,
            "attachments": self._get_leave_attachments(leave),
            "page_name": "leave",
        }
        return request.render("portail.portal_my_leave_edit", values)

    @http.route(["/my/leaves/<int:leave_id>/attachment/<int:attachment_id>"],
                type="http", auth="user", website=True)
    def portal_my_leave_attachment(self, leave_id=None, attachment_id=None, **kw):
        """Justificatif de l'employé (sa propre demande).

        ``?inline=1`` : aperçu dans le navigateur, sinon téléchargement.
        """
        try:
            leave = self._get_leave_or_redirect(leave_id)
            return self._serve_leave_attachment(
                leave, attachment_id, inline=kw.get("inline") == "1")
        except (AccessError, MissingError):
            return request.redirect("/my/leaves")

    @http.route(["/my/leaves/<int:leave_id>/attachment/<int:attachment_id>/delete"],
                type="http", auth="user", website=True, methods=["POST"])
    def portal_my_leave_attachment_delete(self, leave_id=None, attachment_id=None, **post):
        """Suppression d'un justificatif par l'employé, tant que sa demande
        est encore modifiable (pas encore approuvée/refusée)."""
        try:
            leave = self._get_leave_or_redirect(leave_id, require_editable=True)
            self._get_leave_attachment_or_raise(leave, attachment_id).unlink()
        except (AccessError, MissingError):
            return request.redirect("/my/leaves")
        return request.redirect("/my/leaves/%s/edit" % leave.id)

    @http.route(["/my/leaves/<int:leave_id>/cancel"],
                type="http", auth="user", website=True, methods=["POST"])
    def portal_my_leave_cancel(self, leave_id=None, **post):
        try:
            leave = self._get_leave_or_redirect(leave_id, require_editable=True)
        except (AccessError, MissingError):
            return request.redirect("/my/leaves")
        try:
            with self._ecriture_atomique():
                leave.sudo().unlink()
        except (UserError, ValidationError):
            return request.redirect("/my/leaves")
        return request.redirect("/my/leaves?success=cancelled")
