# -*- coding: utf-8 -*-
from odoo import api, models, _


class CalendarEvent(models.Model):
    _inherit = "calendar.event"

    @api.onchange("partner_ids", "start", "stop", "start_date", "stop_date", "allday")
    def _onchange_portail_warn_attendees_on_leave(self):
        """Avertit (sans bloquer) quand un participant a un congé approuvé qui
        chevauche les dates de la réunion.

        Odoo 17 n'a pas d'indicateur d'indisponibilité des participants (il
        arrive dans les versions suivantes) : cet onchange le compense. Les
        employés sont retrouvés à partir des contacts invités — y compris les
        employés « portail » rattachés par ``work_contact_id`` (sans
        utilisateur interne), invisibles pour une simple jointure ``user_id``.
        """
        if not self.partner_ids:
            return
        # Bornes de l'événement, ramenées à des dates
        if self.allday:
            date_from, date_to = self.start_date, self.stop_date
        else:
            date_from = self.start and self.start.date()
            date_to = self.stop and self.stop.date()
        if not date_from or not date_to:
            return

        partner_ids = self.partner_ids.ids
        employees = self.env["hr.employee"].sudo().search([
            "|",
            ("work_contact_id", "in", partner_ids),
            ("user_id.partner_id", "in", partner_ids),
        ])
        if not employees:
            return

        leaves = self.env["hr.leave"].sudo().search([
            ("employee_id", "in", employees.ids),
            ("state", "=", "validate"),
            ("request_date_from", "<=", date_to),
            ("request_date_to", ">=", date_from),
        ], order="request_date_from")
        if not leaves:
            return

        lines = [
            _("• %(name)s est en congé du %(start)s au %(stop)s (%(type)s)",
              name=leave.employee_id.name,
              start=leave.request_date_from.strftime("%d/%m/%Y"),
              stop=leave.request_date_to.strftime("%d/%m/%Y"),
              type=leave.holiday_status_id.name)
            for leave in leaves
        ]
        return {
            "warning": {
                "title": _("Participant(s) indisponible(s)"),
                "message": _(
                    "Attention, ce créneau chevauche un congé approuvé :\n\n%s\n\n"
                    "Vous pouvez tout de même planifier la réunion si nécessaire."
                ) % "\n".join(lines),
            }
        }
