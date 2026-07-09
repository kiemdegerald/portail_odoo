# -*- coding: utf-8 -*-
"""Portail employé — bulletins de paie (/my/payslips)."""
from odoo import http, _
from odoo.http import request
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.addons.portal.controllers.portal import pager as portal_pager

from .portal_common import (
    PortailCommon,
    LEAVE_STATE_LABELS,
    PAYSLIP_VISIBLE_STATES,
)


class PortailPaie(PortailCommon):

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_payslip_or_redirect(self, payslip_id):
        """Retourne le bulletin s'il appartient à l'employé courant, sinon lève."""
        employees = self._get_portal_employees()
        payslip = request.env["hr.payslip"].sudo().browse(payslip_id).exists()
        if not payslip:
            raise MissingError(_("Ce bulletin n'existe pas."))
        if payslip.employee_id not in employees or payslip.state not in PAYSLIP_VISIBLE_STATES:
            raise AccessError(_("Vous n'avez pas accès à ce bulletin."))
        return payslip

    def _payslip_download_filename(self, payslip):
        """Même convention que l'envoi email (custom_salary_reports)."""
        period = payslip.date_from.strftime("%m_%Y") if payslip.date_from else "unknown"
        return "Bulletin_%s_%s.pdf" % (payslip.employee_id.name, period)

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------
    @http.route(["/my/payslips", "/my/payslips/page/<int:page>"],
                type="http", auth="user", website=True)
    def portal_my_payslips(self, page=1, sortby=None, **kw):
        employees = self._get_portal_employees()
        Payslip = request.env["hr.payslip"].sudo()
        domain = self._payslip_domain(employees)

        searchbar_sortings = {
            "date": {"label": _("Période"), "order": "date_from desc"},
            "reference": {"label": _("Référence"), "order": "number desc"},
        }
        if not sortby:
            sortby = "date"
        order = searchbar_sortings[sortby]["order"]

        payslip_count = Payslip.search_count(domain)
        pager = portal_pager(
            url="/my/payslips",
            url_args={"sortby": sortby},
            total=payslip_count,
            page=page,
            step=self._items_per_page,
        )
        payslips = Payslip.search(
            domain, order=order, limit=self._items_per_page, offset=pager["offset"]
        )

        values = {
            "payslips": payslips,
            "page_name": "payslip",
            "pager": pager,
            "default_url": "/my/payslips",
            "searchbar_sortings": searchbar_sortings,
            "sortby": sortby,
        }
        return request.render("portail.portal_my_payslips", values)

    @http.route(["/my/payslips/<int:payslip_id>"], type="http", auth="user", website=True)
    def portal_my_payslip_detail(self, payslip_id=None, **kw):
        try:
            payslip = self._get_payslip_or_redirect(payslip_id)
        except (AccessError, MissingError):
            return request.redirect("/my/payslips")
        values = {
            "payslip": payslip,
            "page_name": "payslip",
            "leave_state_labels": LEAVE_STATE_LABELS,
        }
        return request.render("portail.portal_my_payslip_detail", values)

    @http.route(["/my/payslips/<int:payslip_id>/download"],
                type="http", auth="user", website=True)
    def portal_my_payslip_download(self, payslip_id=None, **kw):
        try:
            payslip = self._get_payslip_or_redirect(payslip_id)
        except (AccessError, MissingError):
            return request.redirect("/my/payslips")

        try:
            pdf_content = payslip._generate_payslip_pdf()
        except UserError:
            return request.redirect("/my/payslips")

        filename = self._payslip_download_filename(payslip)
        headers = [
            ("Content-Type", "application/pdf"),
            ("Content-Length", len(pdf_content)),
            ("Content-Disposition", 'attachment; filename="%s"' % filename),
        ]
        return request.make_response(pdf_content, headers=headers)
