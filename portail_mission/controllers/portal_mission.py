# -*- coding: utf-8 -*-
"""Portail employé — mes missions (/my/missions).

Incrément 1 : consultation (liste, détail).
Incrément 2 : création, modification, soumission, retrait, suppression.

Aucune logique métier ici : le contrôleur collecte les champs, contrôle
l'appartenance de la demande à l'employé de la session, puis appelle les
méthodes de ``gestion_mission`` (action_submit, action_reset_to_draft...)
qui portent TOUTES les règles (dates, chevauchement, photo du circuit et
des montants, retrait réservé au demandeur...).
"""
from datetime import datetime

from odoo import http, _
from odoo.http import request
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from odoo.addons.portal.controllers.portal import pager as portal_pager

from odoo.addons.portail.controllers.portal_common import PortailCommon
from odoo.addons.gestion_mission.models.gm_mission import MISSION_TRANSPORTS

# Libellés FR des statuts de mission (gm.mission.state)
MISSION_STATE_LABELS = {
    "draft": "Brouillon",
    "submitted": "Soumise",
    "validated": "Validée",
    "refused": "Refusée",
}

# Libellés FR des statuts d'une étape du circuit (gm.mission.validation.state)
MISSION_STEP_LABELS = {
    "waiting": "En attente",
    "pending": "À valider",
    "approved": "Approuvée",
    "refused": "Refusée",
}

# Messages de confirmation affichés après une action
MISSION_SUCCESS_MESSAGES = {
    "created": "Votre demande de mission a été enregistrée en brouillon.",
    "submitted": "Votre demande de mission a été soumise pour validation.",
    "updated": "Votre demande de mission a été modifiée.",
    "deleted": "Votre demande de mission a été supprimée.",
    "reset": "Votre demande de mission a été remise en brouillon.",
    "decided": "Votre décision a été enregistrée.",
}


class PortailMission(PortailCommon):

    # ------------------------------------------------------------------
    # Accueil /my : compteurs des cartes + drapeau valideur
    # ------------------------------------------------------------------
    def _is_mission_validator(self):
        """L'utilisateur courant est-il valideur d'au moins une mission
        (une étape de circuit à son nom, quel qu'en soit l'état) ?"""
        employees = self._get_portal_employees()
        if not employees:
            return False
        return bool(request.env["gm.mission.validation"].sudo().search_count(
            [("validator_id", "in", employees.ids)]))

    def _team_missions_to_decide_domain(self, employees):
        """Missions en attente de MA décision, maintenant."""
        return [("state", "=", "submitted"),
                ("current_validator_id", "in", employees.ids)]

    def _prepare_portal_layout_values(self):
        values = super()._prepare_portal_layout_values()
        values["portail_is_mission_validator"] = self._is_mission_validator()
        return values

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        employees = self._get_portal_employees()
        if "mission_count" in counters:
            values["mission_count"] = request.env["gm.mission"].sudo().search_count(
                [("employee_id", "in", employees.ids)]
            ) if employees else 0
        if "team_mission_count" in counters:
            values["team_mission_count"] = request.env["gm.mission"].sudo().search_count(
                self._team_missions_to_decide_domain(employees)
            ) if employees else 0
        return values

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_mission_or_raise(self, mission_id, require_states=None):
        """La mission, après contrôle qu'elle appartient à l'employé courant.

        ``require_states`` restreint en plus aux statuts autorisés pour
        l'action demandée (ex. modifier = brouillon uniquement).
        """
        employees = self._get_portal_employees()
        mission = request.env["gm.mission"].sudo().browse(mission_id).exists()
        if not mission:
            raise MissingError(_("Cette mission n'existe pas."))
        if mission.employee_id not in employees:
            raise AccessError(_("Vous n'avez pas accès à cette mission."))
        if require_states and mission.state not in require_states:
            raise AccessError(_(
                "Cette action n'est plus possible au statut actuel de la "
                "demande."))
        return mission

    def _get_mission_zones(self):
        return request.env["gm.mission.zone"].sudo().search([])

    def _parse_frais_lines(self, error):
        """Lignes « autres frais » du formulaire (paires description /
        montant, lignes vides ignorées). Alimente ``error`` si une ligne
        est incomplète ou invalide."""
        form = request.httprequest.form
        descriptions = form.getlist("frais_description")
        montants = form.getlist("frais_montant")
        lines = []
        for idx, (desc, montant) in enumerate(zip(descriptions, montants), 1):
            desc = (desc or "").strip()
            montant = (montant or "").strip().replace(",", ".").replace(" ", "")
            if not desc and not montant:
                continue
            if not desc:
                error["frais"] = _("Ligne de frais %s : la description est "
                                   "obligatoire.", idx)
                continue
            try:
                value = float(montant)
            except ValueError:
                error["frais"] = _("Ligne de frais %s (« %s ») : montant "
                                   "invalide.", idx, desc)
                continue
            if value <= 0:
                error["frais"] = _("Ligne de frais %s (« %s ») : le montant "
                                   "doit être positif.", idx, desc)
                continue
            lines.append({"description": desc, "montant": value})
        return lines

    def _validate_mission_form(self, post, zones):
        """Valide les champs soumis. Retourne (erreurs, valeurs ORM)."""
        error = {}
        vals = {}

        objet = (post.get("objet") or "").strip()
        if not objet:
            error["objet"] = _("L'objet de la mission est obligatoire.")
        vals["objet"] = objet

        destination = (post.get("destination") or "").strip()
        if not destination:
            error["destination"] = _("La destination est obligatoire.")
        vals["destination"] = destination

        zone_id = (post.get("zone_id") or "").strip()
        if not zone_id.isdigit() or int(zone_id) not in zones.ids:
            error["zone_id"] = _("Veuillez choisir une zone valide.")
        else:
            vals["zone_id"] = int(zone_id)

        transport = (post.get("transport") or "").strip()
        if transport not in dict(MISSION_TRANSPORTS):
            error["transport"] = _("Veuillez choisir un moyen de transport "
                                   "valide.")
        else:
            vals["transport"] = transport

        dates = {}
        for field, label in (("date_depart", _("date de départ")),
                             ("date_retour", _("date de retour"))):
            raw = (post.get(field) or "").strip()
            if not raw:
                dates[field] = False
                continue
            try:
                dates[field] = datetime.strptime(raw, "%Y-%m-%d").date()
            except ValueError:
                error[field] = _("La %s est invalide.", label)
                dates[field] = False
        if dates.get("date_depart") and dates.get("date_retour") \
                and dates["date_retour"] < dates["date_depart"]:
            error["date_retour"] = _(
                "La date de retour ne peut pas précéder la date de départ.")
        vals["date_depart"] = dates.get("date_depart")
        vals["date_retour"] = dates.get("date_retour")

        vals["description"] = (post.get("description") or "").strip() or False

        frais = self._parse_frais_lines(error)
        return error, vals, frais

    def _mission_form_defaults(self, mission=None):
        """Valeurs de pré-remplissage du formulaire."""
        if not mission:
            return {"objet": "", "destination": "", "zone_id": "",
                    "transport": "service", "date_depart": "",
                    "date_retour": "", "description": "", "frais": []}
        return {
            "objet": mission.objet or "",
            "destination": mission.destination or "",
            "zone_id": str(mission.zone_id.id) if mission.zone_id else "",
            "transport": mission.transport or "service",
            "date_depart": mission.date_depart.strftime("%Y-%m-%d")
                           if mission.date_depart else "",
            "date_retour": mission.date_retour.strftime("%Y-%m-%d")
                           if mission.date_retour else "",
            "description": mission.description or "",
            "frais": [{"description": f.description,
                       "montant": "%g" % f.montant}
                      for f in mission.frais_ids],
        }

    def _form_values_from_post(self, post):
        """Re-affichage du formulaire après erreur : valeurs telles que
        saisies (y compris les lignes de frais)."""
        form = request.httprequest.form
        frais = [{"description": d, "montant": m}
                 for d, m in zip(form.getlist("frais_description"),
                                 form.getlist("frais_montant"))
                 if (d or "").strip() or (m or "").strip()]
        return {
            "objet": post.get("objet") or "",
            "destination": post.get("destination") or "",
            "zone_id": post.get("zone_id") or "",
            "transport": post.get("transport") or "service",
            "date_depart": post.get("date_depart") or "",
            "date_retour": post.get("date_retour") or "",
            "description": post.get("description") or "",
            "frais": frais,
        }

    def _render_mission_form(self, mission, form_values, error):
        values = {
            "mission": mission,
            "form_values": form_values,
            "error": error,
            "zones": self._get_mission_zones(),
            "transports": MISSION_TRANSPORTS,
            "page_name": "mission",
        }
        return request.render("portail_mission.portal_my_mission_form", values)

    def _apply_frais(self, mission, frais):
        """Remplace les lignes de frais de la mission par celles du
        formulaire (uniquement en brouillon : verrou métier sinon)."""
        mission.frais_ids.sudo().unlink()
        if frais:
            request.env["gm.mission.frais"].sudo().create([
                dict(line, mission_id=mission.id) for line in frais])

    # ------------------------------------------------------------------
    # Routes — consultation
    # ------------------------------------------------------------------
    @http.route(["/my/missions", "/my/missions/page/<int:page>"],
                type="http", auth="user", website=True)
    def portal_my_missions(self, page=1, **kw):
        employees = self._get_portal_employees()
        Mission = request.env["gm.mission"].sudo()
        domain = [("employee_id", "in", employees.ids)]

        mission_count = Mission.search_count(domain)
        pager = portal_pager(
            url="/my/missions",
            total=mission_count,
            page=page,
            step=self._items_per_page,
        )
        missions = Mission.search(
            domain, order="id desc",
            limit=self._items_per_page, offset=pager["offset"])

        values = {
            "missions": missions,
            "mission_state_labels": MISSION_STATE_LABELS,
            "success_message": MISSION_SUCCESS_MESSAGES.get(kw.get("success")),
            "page_name": "mission",
            "pager": pager,
            "default_url": "/my/missions",
        }
        return request.render("portail_mission.portal_my_missions", values)

    @http.route(["/my/missions/<int:mission_id>"],
                type="http", auth="user", website=True)
    def portal_my_mission_detail(self, mission_id=None, **kw):
        try:
            mission = self._get_mission_or_raise(mission_id)
        except (AccessError, MissingError):
            return request.redirect("/my/missions")
        return self._render_mission_detail(
            mission, success=MISSION_SUCCESS_MESSAGES.get(kw.get("success")))

    def _render_mission_detail(self, mission, success=None, error=None,
                               as_validator=False):
        employees = self._get_portal_employees()
        can_decide_now = (
            as_validator
            and mission.state == "submitted"
            and mission.current_validator_id in employees
            and mission.employee_id not in employees)
        values = {
            "mission": mission,
            "mission_state_labels": MISSION_STATE_LABELS,
            "mission_step_labels": MISSION_STEP_LABELS,
            "success_message": success,
            "error_message": error,
            "is_validator_view": as_validator,
            "can_decide_now": can_decide_now,
            "page_name": "team_mission" if as_validator else "mission",
        }
        return request.render("portail_mission.portal_my_mission_detail", values)

    # ------------------------------------------------------------------
    # Routes — création / modification
    # ------------------------------------------------------------------
    @http.route(["/my/missions/new"],
                type="http", auth="user", website=True, methods=["GET", "POST"])
    def portal_my_mission_new(self, **post):
        employees = self._get_portal_employees()
        if not employees:
            return request.redirect("/my")
        employee = employees[:1]
        zones = self._get_mission_zones()

        if request.httprequest.method == "POST":
            error, vals, frais = self._validate_mission_form(post, zones)
            if not error:
                vals.update({
                    "employee_id": employee.id,
                    "company_id": (employee.company_id
                                   or request.env.company).id,
                })
                mission = request.env["gm.mission"].sudo().create(vals)
                self._apply_frais(mission, frais)
                if post.get("action") == "submit":
                    try:
                        mission.sudo().action_submit()
                        return request.redirect(
                            "/my/missions/%s?success=submitted" % mission.id)
                    except (UserError, ValidationError) as exc:
                        # pas de brouillon fantôme : la demande n'est créée
                        # que si la soumission passe (sinon l'employé
                        # corrige et renvoie le formulaire).
                        mission.frais_ids.sudo().unlink()
                        mission.sudo().unlink()
                        error["global"] = exc.args[0] if exc.args else str(exc)
                else:
                    return request.redirect(
                        "/my/missions/%s?success=created" % mission.id)
            return self._render_mission_form(
                None, self._form_values_from_post(post), error)

        return self._render_mission_form(
            None, self._mission_form_defaults(), {})

    @http.route(["/my/missions/<int:mission_id>/edit"],
                type="http", auth="user", website=True, methods=["GET", "POST"])
    def portal_my_mission_edit(self, mission_id=None, **post):
        try:
            mission = self._get_mission_or_raise(
                mission_id, require_states=("draft",))
        except (AccessError, MissingError):
            return request.redirect("/my/missions")
        zones = self._get_mission_zones()

        if request.httprequest.method == "POST":
            error, vals, frais = self._validate_mission_form(post, zones)
            if not error:
                mission.sudo().write(vals)
                self._apply_frais(mission, frais)
                if post.get("action") == "submit":
                    try:
                        mission.sudo().action_submit()
                        return request.redirect(
                            "/my/missions/%s?success=submitted" % mission.id)
                    except (UserError, ValidationError) as exc:
                        error["global"] = exc.args[0] if exc.args else str(exc)
                else:
                    return request.redirect(
                        "/my/missions/%s?success=updated" % mission.id)
            return self._render_mission_form(
                mission, self._form_values_from_post(post), error)

        return self._render_mission_form(
            mission, self._mission_form_defaults(mission), {})

    # ------------------------------------------------------------------
    # Routes — actions sur une demande existante
    # ------------------------------------------------------------------
    @http.route(["/my/missions/<int:mission_id>/submit"],
                type="http", auth="user", website=True, methods=["POST"])
    def portal_my_mission_submit(self, mission_id=None, **post):
        try:
            mission = self._get_mission_or_raise(
                mission_id, require_states=("draft",))
        except (AccessError, MissingError):
            return request.redirect("/my/missions")
        try:
            mission.sudo().action_submit()
        except (UserError, ValidationError) as exc:
            return self._render_mission_detail(
                mission, error=exc.args[0] if exc.args else str(exc))
        return request.redirect(
            "/my/missions/%s?success=submitted" % mission.id)

    @http.route(["/my/missions/<int:mission_id>/reset"],
                type="http", auth="user", website=True, methods=["POST"])
    def portal_my_mission_reset(self, mission_id=None, **post):
        """Retrait d'une demande soumise (par son demandeur) ou reprise
        d'une demande refusée — la règle vit dans action_reset_to_draft."""
        try:
            mission = self._get_mission_or_raise(
                mission_id, require_states=("submitted", "refused"))
        except (AccessError, MissingError):
            return request.redirect("/my/missions")
        employee = self._get_portal_employees()[:1]
        try:
            mission.sudo().with_context(
                gm_actor_employee_id=employee.id).action_reset_to_draft()
        except (UserError, ValidationError) as exc:
            return self._render_mission_detail(
                mission, error=exc.args[0] if exc.args else str(exc))
        return request.redirect("/my/missions/%s?success=reset" % mission.id)

    @http.route(["/my/missions/<int:mission_id>/delete"],
                type="http", auth="user", website=True, methods=["POST"])
    def portal_my_mission_delete(self, mission_id=None, **post):
        try:
            mission = self._get_mission_or_raise(
                mission_id, require_states=("draft",))
        except (AccessError, MissingError):
            return request.redirect("/my/missions")
        mission.frais_ids.sudo().unlink()
        mission.sudo().unlink()
        return request.redirect("/my/missions?success=deleted")

    # ------------------------------------------------------------------
    # Téléchargement des documents officiels (mission validée)
    # ------------------------------------------------------------------
    PM_DOCUMENTS = {
        "ordre": ("gestion_mission.report_gm_ordre_mission",
                  "Ordre de mission"),
        "decompte": ("gestion_mission.report_gm_decompte",
                     "Fiche de decompte"),
    }

    @http.route(["/my/missions/<int:mission_id>/document/<string:doc>"],
                type="http", auth="user", website=True)
    def portal_my_mission_document(self, mission_id=None, doc=None, **kw):
        """PDF officiel (ordre de mission / fiche de décompte).

        Réservé aux missions VALIDÉES (mêmes conditions que les boutons
        du backend : pas de document sans numéro officiel), pour le
        demandeur OU un valideur de son circuit.
        """
        if doc not in self.PM_DOCUMENTS:
            return request.redirect("/my/missions")
        employees = self._get_portal_employees()
        mission = request.env["gm.mission"].sudo().browse(mission_id).exists()
        allowed = mission and (
            mission.employee_id in employees
            or mission.validation_line_ids.filtered(
                lambda l: l.validator_id in employees))
        if not (allowed and mission.state == "validated"):
            return request.redirect("/my/missions")

        report_ref, label = self.PM_DOCUMENTS[doc]
        pdf, _kind = request.env["ir.actions.report"].sudo()._render_qweb_pdf(
            report_ref, [mission.id])
        filename = "%s %s.pdf" % (label, (mission.name or "").replace("/", "-"))
        disposition = "inline" if kw.get("inline") == "1" else "attachment"
        return request.make_response(pdf, headers=[
            ("Content-Type", "application/pdf"),
            ("Content-Length", len(pdf)),
            ("Content-Disposition",
             '%s; filename="%s"' % (disposition, filename)),
            ("X-Content-Type-Options", "nosniff"),
        ])

    # ------------------------------------------------------------------
    # Espace valideur : missions de mon périmètre
    # ------------------------------------------------------------------
    def _get_team_mission_or_raise(self, mission_id):
        """La mission, après contrôle que l'employé courant est valideur
        d'au moins une étape de SON circuit (photo)."""
        employees = self._get_portal_employees()
        mission = request.env["gm.mission"].sudo().browse(mission_id).exists()
        if not mission:
            raise MissingError(_("Cette mission n'existe pas."))
        if not mission.validation_line_ids.filtered(
                lambda l: l.validator_id in employees):
            raise AccessError(_("Vous n'êtes pas valideur de cette mission."))
        return mission

    @http.route(["/my/team/missions", "/my/team/missions/page/<int:page>"],
                type="http", auth="user", website=True)
    def portal_team_missions(self, page=1, **kw):
        employees = self._get_portal_employees()
        Mission = request.env["gm.mission"].sudo()

        to_decide = Mission.search(
            self._team_missions_to_decide_domain(employees), order="id desc")

        # historique : toutes les missions où je figure dans le circuit
        domain = [("validation_line_ids.validator_id", "in", employees.ids),
                  ("id", "not in", to_decide.ids)]
        history_count = Mission.search_count(domain)
        pager = portal_pager(
            url="/my/team/missions",
            total=history_count,
            page=page,
            step=self._items_per_page,
        )
        history = Mission.search(
            domain, order="id desc",
            limit=self._items_per_page, offset=pager["offset"])

        values = {
            "to_decide": to_decide,
            "history": history,
            "mission_state_labels": MISSION_STATE_LABELS,
            "success_message": MISSION_SUCCESS_MESSAGES.get(kw.get("success")),
            "page_name": "team_mission",
            "pager": pager,
            "default_url": "/my/team/missions",
        }
        return request.render("portail_mission.portal_team_missions", values)

    @http.route(["/my/team/missions/<int:mission_id>"],
                type="http", auth="user", website=True)
    def portal_team_mission_detail(self, mission_id=None, **kw):
        try:
            mission = self._get_team_mission_or_raise(mission_id)
        except (AccessError, MissingError):
            return request.redirect("/my/team/missions")
        return self._render_mission_detail(
            mission, success=MISSION_SUCCESS_MESSAGES.get(kw.get("success")),
            as_validator=True)

    @http.route(["/my/team/missions/<int:mission_id>/decide"],
                type="http", auth="user", website=True, methods=["POST"])
    def portal_team_mission_decide(self, mission_id=None, **post):
        """Décision du valideur : approuver / refuser / renvoyer.

        Toutes les règles (bon valideur, bonne étape, séparation des
        tâches, commentaire obligatoire au refus/renvoi) sont dans
        gestion_mission — l'employé AUTHENTIFIÉ est transmis en contexte.
        """
        try:
            mission = self._get_team_mission_or_raise(mission_id)
        except (AccessError, MissingError):
            return request.redirect("/my/team/missions")
        employee = self._get_portal_employees()[:1]
        action = post.get("action")
        comment = (post.get("comment") or "").strip() or None
        mission_ctx = mission.sudo().with_context(
            gm_actor_employee_id=employee.id)
        try:
            if action == "approve":
                mission_ctx.action_approve_step(comment=comment)
            elif action == "refuse":
                mission_ctx.action_refuse_step(comment=comment)
            elif action == "send_back":
                mission_ctx.action_send_back(comment=comment)
            else:
                raise UserError(_("Action inconnue."))
        except (UserError, ValidationError) as exc:
            return self._render_mission_detail(
                mission, error=exc.args[0] if exc.args else str(exc),
                as_validator=True)
        return request.redirect("/my/team/missions?success=decided")
