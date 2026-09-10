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
import base64
from datetime import datetime

from odoo import http, _
from odoo.http import request
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from odoo.addons.portal.controllers.portal import pager as portal_pager

from odoo.addons.portail.controllers.portal_common import (
    PortailCommon,
    validate_justificatif,
)
from odoo.addons.gestion_mission.models.gm_mission import MISSION_TRANSPORTS

# Libellés FR des statuts de mission (gm.mission.state)
MISSION_STATE_LABELS = {
    "draft": "Brouillon",
    "submitted": "Soumise",
    "validated": "Validée",
    "returned": "Retour déclaré",
    "closed": "Clôturée",
    "refused": "Refusée",
    "cancelled": "Annulée",
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
    "returned": "Votre retour de mission a été déclaré. Le décompte "
                "définitif est calculé ; le service RH le vérifie avant "
                "le règlement du solde.",
    "justificatifs": "Vos justificatifs ont été déposés. La mission pourra être clôturée quand tous les missionnaires auront fourni les leurs.",
    "created_for": "Le brouillon a été créé pour votre collaborateur : il "
                   "pourra le compléter et le soumettre depuis son portail.",
    "submitted_for": "La demande a été soumise au nom de votre collaborateur.",
}


class PortailMission(PortailCommon):

    # ------------------------------------------------------------------
    # Accueil /my : compteurs des cartes + drapeau valideur
    # ------------------------------------------------------------------
    def _gm_can(self, key):
        """Réglage « qui peut initier » (Paramètres > Missions), "1"/"0"."""
        return request.env["ir.config_parameter"].sudo().get_param(
            key, "1") == "1"

    def _get_direct_reports(self, employees):
        """Collaborateurs DIRECTS (parent_id) de l'employé courant."""
        if not employees:
            return request.env["hr.employee"].sudo()
        return request.env["hr.employee"].sudo().search(
            [("parent_id", "in", employees.ids)])

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
                self._my_missions_domain(employees)
            ) if employees else 0
        if "team_mission_count" in counters:
            values["team_mission_count"] = request.env["gm.mission"].sudo().search_count(
                self._team_missions_to_decide_domain(employees)
            ) if employees else 0
        return values

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _my_missions_domain(self, employees):
        """Les missions de l'employé : celles dont il est demandeur (chef
        de mission) OU MEMBRE (missions groupées)."""
        return ["|", ("employee_id", "in", employees.ids),
                ("membre_ids.employee_id", "in", employees.ids)]

    def _get_mission_or_raise(self, mission_id, require_states=None,
                              require_chef=False):
        """La mission, après contrôle que l'employé courant en est le CHEF
        (demandeur) ou un MEMBRE.

        ``require_states`` restreint aux statuts autorisés pour l'action ;
        ``require_chef`` réserve l'action au chef de mission (modifier,
        soumettre, retirer, supprimer — un simple membre consulte).
        """
        employees = self._get_portal_employees()
        mission = request.env["gm.mission"].sudo().browse(mission_id).exists()
        if not mission:
            raise MissingError(_("Cette mission n'existe pas."))
        is_chef = mission.employee_id in employees
        is_member = bool(mission.membre_ids.employee_id & employees)
        if not (is_chef or is_member):
            raise AccessError(_("Vous n'avez pas accès à cette mission."))
        if require_chef and not is_chef:
            raise AccessError(_(
                "Seul le chef de mission peut effectuer cette action."))
        if require_states and mission.state not in require_states:
            raise AccessError(_(
                "Cette action n'est plus possible au statut actuel de la "
                "demande."))
        return mission

    def _get_mission_zones(self):
        return request.env["gm.mission.zone"].sudo().search([])

    def _parse_frais_lines(self, error, allowed_emp_ids=None):
        """Lignes « autres frais » du formulaire (description / montant /
        missionnaire, lignes vides ignorées). ``allowed_emp_ids`` : ids
        d'employés autorisés comme missionnaire (None = ignorer le champ).
        Alimente ``error`` si une ligne est incomplète ou invalide."""
        form = request.httprequest.form
        descriptions = form.getlist("frais_description")
        montants = form.getlist("frais_montant")
        membres = form.getlist("frais_membre")
        lines = []
        for idx, (desc, montant) in enumerate(zip(descriptions, montants), 1):
            desc = (desc or "").strip()
            montant = (montant or "").strip().replace(",", ".").replace(" ", "")
            membre = (membres[idx - 1] if idx - 1 < len(membres) else "").strip()
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
            employee_id = None
            if allowed_emp_ids is not None and membre:
                if membre.isdigit() and int(membre) in allowed_emp_ids:
                    employee_id = int(membre)
                else:
                    error["frais"] = _(
                        "Ligne de frais %s (« %s ») : le missionnaire "
                        "choisi n'est pas membre de la mission.", idx, desc)
                    continue
            lines.append({"description": desc, "montant": value,
                          "employee_id": employee_id})
        return lines

    def _validate_mission_form(self, post, zones, allowed_emp_ids=None):
        """Valide les champs soumis. Retourne (erreurs, valeurs ORM,
        lignes de frais). ``allowed_emp_ids`` : employés qui peuvent être
        missionnaires des frais (None = champ ignoré)."""
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

        # Une plaque n'a de sens que pour un véhicule de service : pour
        # tout autre transport on l'efface, sinon elle resterait en base
        # et s'imprimerait sur l'ordre de mission.
        vals["immatriculation"] = (
            (post.get("immatriculation") or "").strip() or False
            if transport == "service" else False)

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

        frais = self._parse_frais_lines(error, allowed_emp_ids)
        return error, vals, frais

    def _mission_form_defaults(self, mission=None):
        """Valeurs de pré-remplissage du formulaire."""
        if not mission:
            return {"objet": "", "destination": "", "zone_id": "",
                    "transport": "service", "immatriculation": "",
                    "date_depart": "", "date_retour": "",
                    "description": "", "frais": []}
        return {
            "objet": mission.objet or "",
            "destination": mission.destination or "",
            "zone_id": str(mission.zone_id.id) if mission.zone_id else "",
            "transport": mission.transport or "service",
            "immatriculation": mission.immatriculation or "",
            "date_depart": mission.date_depart.strftime("%Y-%m-%d")
                           if mission.date_depart else "",
            "date_retour": mission.date_retour.strftime("%Y-%m-%d")
                           if mission.date_retour else "",
            "description": mission.description or "",
            "frais": [{"description": f.description,
                       "montant": "%g" % f.montant,
                       "employee_id": f.membre_id.employee_id.id or ""}
                      for f in self._frais_prevus(mission)],
        }

    def _form_values_from_post(self, post):
        """Re-affichage du formulaire après erreur : valeurs telles que
        saisies (y compris les lignes de frais)."""
        form = request.httprequest.form
        membres = form.getlist("frais_membre")
        frais = []
        for i, (d, m) in enumerate(zip(form.getlist("frais_description"),
                                       form.getlist("frais_montant"))):
            if (d or "").strip() or (m or "").strip():
                frais.append({"description": d, "montant": m,
                              "employee_id": (membres[i]
                                              if i < len(membres) else "")})
        return {
            "objet": post.get("objet") or "",
            "destination": post.get("destination") or "",
            "zone_id": post.get("zone_id") or "",
            "transport": post.get("transport") or "service",
            "immatriculation": post.get("immatriculation") or "",
            "date_depart": post.get("date_depart") or "",
            "date_retour": post.get("date_retour") or "",
            "description": post.get("description") or "",
            "frais": frais,
        }

    def _render_mission_form(self, mission, form_values, error, **extra):
        values = {
            "mission": mission,
            "form_values": form_values,
            "error": error,
            "zones": self._get_mission_zones(),
            "transports": MISSION_TRANSPORTS,
            "team_mode": False,
            "page_name": "mission",
        }
        values.update(extra)
        return request.render("portail_mission.portal_my_mission_form", values)

    @staticmethod
    def _frais_prevus(mission):
        """Lignes PRÉVUES d'une mission (le portail ne saisit que
        celles-là ; les frais réels arrivent avec le retour)."""
        return mission.frais_ids.filtered(lambda f: f.type_frais == "prevu")

    def _apply_frais(self, mission, frais):
        """Remplace les lignes de frais de la mission par celles du
        formulaire (uniquement en brouillon : verrou métier sinon). Le
        missionnaire est résolu employé -> ligne membre ; sans choix, le
        frais ira au chef de mission à la soumission."""
        self._frais_prevus(mission).sudo().unlink()
        if frais:
            emp_to_membre = {m.employee_id.id: m.id
                             for m in mission.membre_ids}
            request.env["gm.mission.frais"].sudo().create([
                {"mission_id": mission.id,
                 "description": line["description"],
                 "montant": line["montant"],
                 "type_frais": "prevu",
                 "membre_id": emp_to_membre.get(line.get("employee_id"))
                              or False}
                for line in frais])

    # ------------------------------------------------------------------
    # Routes — consultation
    # ------------------------------------------------------------------
    @http.route(["/my/missions", "/my/missions/page/<int:page>"],
                type="http", auth="user", website=True)
    def portal_my_missions(self, page=1, **kw):
        employees = self._get_portal_employees()
        Mission = request.env["gm.mission"].sudo()
        domain = self._my_missions_domain(employees)

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
            "can_create": bool(employees) and self._gm_can(
                "gm.portal_employee_can_create"),
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
            and not (mission.membre_ids.employee_id & employees)
            and mission.employee_id not in employees)
        values = {
            "mission": mission,
            "mission_state_labels": MISSION_STATE_LABELS,
            "mission_step_labels": MISSION_STEP_LABELS,
            "success_message": success,
            "error_message": error,
            "is_validator_view": as_validator,
            "is_chef": mission.employee_id in employees,
            # Le CHEF déclare les dates ; chaque MEMBRE vient déposer ses
            # justificatifs — y compris après la déclaration du retour,
            # tant que la mission n'est pas clôturée.
            "can_declare_return": (mission.state == "validated"
                                   and mission.employee_id in employees),
            # Le chef aussi doit pouvoir revenir déposer SES pièces une
            # fois le retour déclaré : sans cela il n'avait plus aucun
            # lien, et la mission restait impossible à clôturer.
            "can_deposer_pieces": (
                mission.state in ("validated", "returned")
                and bool(mission.membre_ids.employee_id & employees)
                and not (mission.state == "validated"
                         and mission.employee_id in employees)),
            "mes_pieces_manquantes": len(mission.indemnite_ids.filtered(
                lambda l: l.membre_id.employee_id
                in employees)._incompletes()),
            "can_decide_now": can_decide_now,
            # Le tableau des membres suit le MÊME réglage que la fiche
            # imprimée : si la banque a choisi que chacun ne voie que sa
            # ligne, l'écran du portail ne doit pas dire le contraire.
            "membres_visibles": (
                mission.membre_ids.filtered(
                    lambda x: x.employee_id in employees)
                if self._membre_du_decompte(mission, employees)
                else mission.membre_ids),
            # Les totaux affichés : ceux du GROUPE pour le chef et les
            # valideurs, ceux du MISSIONNAIRE quand chacun ne voit que sa
            # ligne. Les deux objets portent les mêmes champs, seul le
            # périmètre change.
            "totaux": (self._membre_du_decompte(mission, employees)
                       or mission),
            # Le libellé du solde doit dire de QUOI on parle : le
            # trop-perçu du groupe entier n'est pas celui du lecteur.
            "totaux_global": not self._membre_du_decompte(
                mission, employees),
            # Sa propre déclaration : l'état où la RH l'a laissée, et le
            # motif si elle la lui a renvoyée.
            "ma_declaration": mission.membre_ids.filtered(
                lambda m: m.employee_id in employees)[:1],
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
        if not employees or not self._gm_can("gm.portal_employee_can_create"):
            return request.redirect("/my/missions")
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
                        with self._ecriture_atomique():
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
                mission_id, require_states=("draft",), require_chef=True)
        except (AccessError, MissingError):
            return request.redirect("/my/missions")
        zones = self._get_mission_zones()

        if request.httprequest.method == "POST":
            error, vals, frais = self._validate_mission_form(
                post, zones,
                allowed_emp_ids=mission.membre_ids.employee_id.ids)
            if not error:
                mission.sudo().write(vals)
                self._apply_frais(mission, frais)
                if post.get("action") == "submit":
                    try:
                        with self._ecriture_atomique():
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
                mission_id, require_states=("draft",), require_chef=True)
        except (AccessError, MissingError):
            return request.redirect("/my/missions")
        try:
            with self._ecriture_atomique():
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
                mission_id, require_states=("submitted", "refused"),
                require_chef=True)
        except (AccessError, MissingError):
            return request.redirect("/my/missions")
        employee = self._get_portal_employees()[:1]
        try:
            with self._ecriture_atomique():
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
                mission_id, require_states=("draft",), require_chef=True)
        except (AccessError, MissingError):
            return request.redirect("/my/missions")
        mission.frais_ids.sudo().unlink()
        mission.membre_ids.sudo().unlink()
        mission.sudo().unlink()
        return request.redirect("/my/missions?success=deleted")

    # ------------------------------------------------------------------
    # Retour de mission (note de frais) — réservé au CHEF DE MISSION
    # ------------------------------------------------------------------
    def _parse_frais_reels(self, mission, error, membres=None):
        """Lignes de frais réels du formulaire de retour : montant,
        description, missionnaire, et justificatif éventuel (fichier
        téléversé ou pièce déjà enregistrée)."""
        form = request.httprequest.form
        files = request.httprequest.files
        emp_ok = (membres if membres is not None
                  else mission.membre_ids).employee_id.ids
        lines = []
        descriptions = form.getlist("reel_description")
        montants = form.getlist("reel_montant")
        membres = form.getlist("reel_membre")
        garder = form.getlist("reel_garder")
        justificatifs = files.getlist("reel_justificatif")
        for idx, (desc, montant) in enumerate(zip(descriptions, montants)):
            desc = (desc or "").strip()
            brut = (montant or "").strip().replace(",", ".").replace(" ", "")
            if not desc and not brut:
                continue
            if not desc:
                error["frais"] = _("Ligne %s : la description est "
                                   "obligatoire.", idx + 1)
                continue
            try:
                valeur = float(brut)
            except ValueError:
                error["frais"] = _("Ligne %s (« %s ») : montant invalide.",
                                   idx + 1, desc)
                continue
            if valeur <= 0:
                error["frais"] = _("Ligne %s (« %s ») : le montant doit "
                                   "être positif.", idx + 1, desc)
                continue
            membre = membres[idx] if idx < len(membres) else ""
            employee_id = None
            if membre:
                if membre.isdigit() and int(membre) in emp_ok:
                    employee_id = int(membre)
                else:
                    error["frais"] = _(
                        "Ligne %s : le missionnaire choisi n'est pas "
                        "membre de la mission.", idx + 1)
                    continue
            fichier = justificatifs[idx] if idx < len(justificatifs) else None
            lines.append({
                "description": desc,
                "montant": valeur,
                "employee_id": employee_id,
                "file": fichier if (fichier and fichier.filename) else None,
                "garder": (garder[idx] if idx < len(garder) else "") == "1",
            })
        return lines

    def _apply_frais_reels(self, mission, lines, membres=None):
        """Remplace les frais réels par ceux du formulaire, en conservant
        le justificatif déjà enregistré quand aucun nouveau fichier n'est
        envoyé.

        ``membres`` borne le remplacement aux lignes de CES missionnaires.
        Sans cette borne, un membre qui déclarait ses frais effaçait ceux
        de ses collègues : chacun ne poste que son propre tableau.
        """
        concernes = membres if membres is not None else mission.membre_ids
        anciennes = mission.frais_reels_ids.filtered(
            lambda f: f.membre_id in concernes)
        anciens = {}
        for ligne in anciennes:
            anciens[(ligne.description, ligne.membre_id.id)] = (
                ligne.justificatif, ligne.justificatif_filename)
        anciennes.sudo().unlink()
        emp_to_membre = {m.employee_id.id: m.id for m in concernes}
        defaut = concernes[:1].id
        for ligne in lines:
            membre_id = emp_to_membre.get(ligne.get("employee_id")) or defaut
            vals = {
                "mission_id": mission.id,
                "membre_id": membre_id,
                "type_frais": "reel",
                "description": ligne["description"],
                "montant": ligne["montant"],
            }
            if ligne.get("file"):
                contenu = ligne["file"].read() or b""
                validate_justificatif(ligne["file"].filename, contenu)
                vals["justificatif"] = base64.b64encode(contenu)
                vals["justificatif_filename"] = ligne["file"].filename
            elif ligne.get("garder"):
                ancien = anciens.get((ligne["description"], membre_id))
                if ancien and ancien[0]:
                    vals["justificatif"] = ancien[0]
                    vals["justificatif_filename"] = ancien[1]
            request.env["gm.mission.frais"].sudo().create(vals)

    def _enregistrer_depenses(self, lignes, error):
        """Le montant réellement dépensé, saisi en regard du montant reçu.

        Sur TOUTES ses lignes : une indemnité forfaitaire lui est
        acquise, mais rien n'empêche l'agent de dire ce qu'elle lui a
        réellement coûté. Seules les lignes « à justifier » l'exigent —
        c'est le contrôle métier qui le vérifie, pas la saisie.
        """
        form = request.httprequest.form
        for ligne in lignes:
            brut = (form.get("indem_depense_%s" % ligne.id) or "").strip()
            brut = brut.replace(",", ".").replace(" ", "")
            if not brut:
                continue
            try:
                valeur = float(brut)
            except ValueError:
                error["depenses"] = _(
                    "« %s » : le montant dépensé est invalide.",
                    ligne.type_id.name or "")
                return
            if valeur < 0:
                error["depenses"] = _(
                    "« %s » : le montant dépensé ne peut pas être négatif.",
                    ligne.type_id.name or "")
                return
            ligne.sudo().montant_depense = valeur

    def _enregistrer_justificatifs(self, lignes, error):
        """Dépose les pièces sur les lignes d'indemnité du missionnaire.

        Le fichier est validé comme les justificatifs de frais : type
        détecté depuis le CONTENU, taille bornée.
        """
        fichiers = request.httprequest.files
        for ligne in lignes:
            envoye = fichiers.get("indem_justif_%s" % ligne.id)
            if not envoye or not envoye.filename:
                continue
            contenu = envoye.read()
            if not contenu:
                continue
            try:
                validate_justificatif(envoye.filename, contenu)
            except ValidationError as exc:
                error["justificatifs"] = exc.args[0] if exc.args else str(exc)
                return
            ligne.sudo().write({
                "justificatif": base64.b64encode(contenu),
                "justificatif_filename": envoye.filename,
            })

    def _enregistrer_visas(self, mission, error):
        """Dépose les documents visés au départ et au retour.

        Seul le chef de mission passe ici : les dates réelles valent pour
        le groupe entier, les visas qui les prouvent aussi. Un champ vide
        laisse en place la pièce déjà déposée — le chef peut revenir
        corriger l'une sans redéposer l'autre.
        """
        if not mission.visa_exige:
            return
        fichiers = request.httprequest.files
        vals = {}
        for champ in ("visa_depart", "visa_retour"):
            envoye = fichiers.get(champ)
            if not envoye or not envoye.filename:
                continue
            contenu = envoye.read()
            if not contenu:
                continue
            try:
                validate_justificatif(envoye.filename, contenu)
            except ValidationError as exc:
                error["visas"] = exc.args[0] if exc.args else str(exc)
                return
            vals[champ] = base64.b64encode(contenu)
            vals["%s_filename" % champ] = envoye.filename
        if vals:
            mission.sudo().write(vals)

    def _retour_form_values(self, mission, post=None):
        """Valeurs du formulaire de retour : depuis la mission, ou depuis
        la saisie en cours après une erreur."""
        if post is None:
            return {
                "date_depart_reelle": mission.date_depart_reelle.strftime("%Y-%m-%d")
                    if mission.date_depart_reelle else (
                        mission.date_depart.strftime("%Y-%m-%d")
                        if mission.date_depart else ""),
                "date_retour_reelle": mission.date_retour_reelle.strftime("%Y-%m-%d")
                    if mission.date_retour_reelle else (
                        mission.date_retour.strftime("%Y-%m-%d")
                        if mission.date_retour else ""),
                "retour_commentaire": mission.retour_commentaire or "",
                "visa_depart": mission.visa_depart_filename or "",
                "visa_retour": mission.visa_retour_filename or "",
                "frais": [{"description": f.description,
                           "montant": "%g" % f.montant,
                           "employee_id": f.membre_id.employee_id.id or "",
                           "justificatif": f.justificatif_filename or ""}
                          for f in (mission.frais_reels_ids
                                    or mission.frais_prevus_ids).filtered(
                              lambda x: x.membre_id.employee_id
                              in self._get_portal_employees())],
            }
        form = request.httprequest.form
        membres = form.getlist("reel_membre")
        frais = []
        for i, (d, m) in enumerate(zip(form.getlist("reel_description"),
                                       form.getlist("reel_montant"))):
            if (d or "").strip() or (m or "").strip():
                frais.append({
                    "description": d, "montant": m,
                    "employee_id": membres[i] if i < len(membres) else "",
                    "justificatif": "",
                })
        return {
            "date_depart_reelle": post.get("date_depart_reelle") or "",
            "date_retour_reelle": post.get("date_retour_reelle") or "",
            "retour_commentaire": post.get("retour_commentaire") or "",
            "visa_depart": mission.visa_depart_filename or "",
            "visa_retour": mission.visa_retour_filename or "",
            "frais": frais,
        }

    @http.route(["/my/missions/<int:mission_id>/retour"],
                type="http", auth="user", website=True,
                methods=["GET", "POST"])
    def portal_my_mission_retour(self, mission_id=None, **post):
        try:
            # Ouvert à TOUS les missionnaires : chacun dépose ses propres
            # justificatifs et déclare ses frais. Seul le CHEF saisit les
            # dates réelles — elles valent pour le groupe entier, puisque
            # tout le monde rentre ensemble.
            mission = self._get_mission_or_raise(
                mission_id, require_states=("validated", "returned"))
        except (AccessError, MissingError):
            return request.redirect("/my/missions")
        employees = self._get_portal_employees()
        est_chef = mission.employee_id in employees
        # Une déclaration VALIDÉE par la RH est close : l'agent ne la
        # retouche plus. La RH garde la main depuis le back-office.
        mes_lignes = mission.indemnite_ids.filtered(
            lambda l: l.membre_id.employee_id in employees
            and l.membre_id.retour_state != "valide")

        error = {}
        if request.httprequest.method == "POST":
            # Les justificatifs d'indemnité : chacun ne dépose que sur SES
            # lignes — le filtre ci-dessus est la seule porte.
            # Le montant dépensé d'abord : la pièce qui suit vient
            # prouver ce chiffre-là.
            self._enregistrer_depenses(mes_lignes, error)
            self._enregistrer_justificatifs(mes_lignes, error)
            # Les visas prouvent les dates réelles : c'est le chef qui les
            # saisit, c'est donc lui qui dépose les pièces.
            if est_chef:
                self._enregistrer_visas(mission, error)
            # Chacun ne déclare QUE ses propres frais : le remplacement est
            # borné à ses lignes, celles des collègues ne bougent pas.
            mes_membres = mission.membre_ids.filtered(
                lambda m: m.employee_id in employees)
            # Les frais RÉELS n'existent qu'une fois le retour déclaré : le
            # chef les saisit dans le même mouvement, les autres ensuite.
            lignes = (self._parse_frais_reels(mission, error, mes_membres)
                      if est_chef or mission.state == "returned" else [])
            if not est_chef:
                if not error:
                    if mission.state == "returned":
                        self._apply_frais_reels(mission, lignes, mes_membres)
                    # Sa déclaration part à la RH : c'est ce dépôt-là qui
                    # la fait passer de « à déclarer » à « déclarée ».
                    mes_membres.sudo()._marquer_declaree()
                    return request.redirect(
                        "/my/missions/%s?success=justificatifs" % mission.id)
                post = dict(post)
            if not error:
                vals = {
                    "date_depart_reelle": (post.get("date_depart_reelle")
                                           or "").strip() or False,
                    "date_retour_reelle": (post.get("date_retour_reelle")
                                           or "").strip() or False,
                    "retour_commentaire": (post.get("retour_commentaire")
                                           or "").strip() or False,
                }
                try:
                    with self._ecriture_atomique():
                        mission.sudo().write(vals)
                        # les frais réels n'acceptent l'écriture qu'à l'état
                        # « returned » : on déclare d'abord, on remplace ensuite.
                        # Le retour peut déjà avoir été déclaré — le chef
                        # revient alors seulement compléter ses pièces.
                        if mission.state == "validated":
                            mission.sudo().action_declare_return()
                        else:
                            # retour déjà déclaré : le chef revient compléter,
                            # sa déclaration repart à la RH.
                            mes_membres.sudo()._marquer_declaree()
                        self._apply_frais_reels(mission, lignes, mes_membres)
                        return request.redirect(
                            "/my/missions/%s?success=returned" % mission.id)
                except (UserError, ValidationError) as exc:
                    if mission.state == "returned":
                        mission.sudo().action_back_to_validated()
                    error["global"] = exc.args[0] if exc.args else str(exc)

        values = {
            "mission": mission,
            "form_values": self._retour_form_values(
                mission, post if request.httprequest.method == "POST" else None),
            "error": error,
            "est_chef": est_chef,
            # Chacun ne voit QUE ses propres lignes d'indemnité.
            "mes_lignes": mes_lignes,
            "page_name": "mission",
        }
        return request.render(
            "portail_mission.portal_my_mission_retour", values)

    # ------------------------------------------------------------------
    # Téléchargement des documents officiels (mission validée)
    # ------------------------------------------------------------------
    PM_DOCUMENTS = {
        "ordre": ("gestion_mission.report_gm_ordre_mission",
                  "Ordre de mission"),
        "decompte": ("gestion_mission.report_gm_decompte",
                     "Fiche de decompte"),
    }

    def _membre_du_decompte(self, mission, employees):
        """La ligne à laquelle limiter le décompte, ou None pour la fiche
        complète.

        None dans trois cas : le réglage est décoché, l'utilisateur est le
        chef de mission, ou il est valideur du circuit.
        """
        actif = request.env["ir.config_parameter"].sudo().get_param(
            "gm.decompte_individuel", "0") == "1"
        if not actif:
            return None
        if mission.employee_id in employees:
            return None
        if mission.validation_line_ids.filtered(
                lambda l: l.validator_id in employees):
            return None
        return mission.membre_ids.filtered(
            lambda m: m.employee_id in employees)[:1] or None

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
        # demandeur, MEMBRE (décision : tous les membres voient la fiche
        # complète) ou valideur du circuit
        allowed = mission and (
            mission.employee_id in employees
            or (mission.membre_ids.employee_id & employees)
            or mission.validation_line_ids.filtered(
                lambda l: l.validator_id in employees))
        if not (allowed
                and mission.state in ("validated", "returned", "closed")):
            return request.redirect("/my/missions")

        report_ref, label = self.PM_DOCUMENTS[doc]
        rendu = request.env["ir.actions.report"].sudo()
        # Décompte individuel : réglage de la banque. Le chef de mission et
        # les valideurs gardent la fiche complète — le premier répond du
        # dossier, les seconds statuent sur le total du groupe. Seul un
        # SIMPLE membre est ramené à sa propre ligne.
        membre = self._membre_du_decompte(mission, employees)             if doc == "decompte" else None
        if membre:
            rendu = rendu.with_context(gm_decompte_membre_id=membre.id)
            label = "Decompte individuel"
        pdf, _kind = rendu._render_qweb_pdf(report_ref, [mission.id])
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
            "can_create_for_team": bool(self._get_direct_reports(employees))
                                   and self._gm_can("gm.portal_chef_can_create"),
            "page_name": "team_mission",
            "pager": pager,
            "default_url": "/my/team/missions",
        }
        return request.render("portail_mission.portal_team_missions", values)

    @http.route(["/my/team/missions/new"],
                type="http", auth="user", website=True, methods=["GET", "POST"])
    def portal_team_mission_new(self, **post):
        """Le chef de service crée une demande AU NOM d'un collaborateur
        direct : brouillon (l'agent complète et soumet — modèle délégué)
        ou soumission directe. Canal activable dans Paramètres > Missions."""
        employees = self._get_portal_employees()
        reports = self._get_direct_reports(employees)
        if not reports or not self._gm_can("gm.portal_chef_can_create"):
            return request.redirect("/my/team/missions")
        # périmètre décidé : ses collaborateurs directs + lui-même
        pool = reports | employees
        zones = self._get_mission_zones()

        if request.httprequest.method == "POST":
            error, vals, frais = self._validate_mission_form(
                post, zones, allowed_emp_ids=pool.ids)
            emp_id = (post.get("employee_id") or "").strip()
            if not emp_id.isdigit() or int(emp_id) not in pool.ids:
                error["employee_id"] = _(
                    "Veuillez choisir le chef de mission parmi vos "
                    "collaborateurs directs (ou vous-même).")
            membre_ids = []
            for raw in request.httprequest.form.getlist("membre_ids"):
                if raw.isdigit() and int(raw) in pool.ids:
                    membre_ids.append(int(raw))
                elif raw:
                    error["membre_ids"] = _(
                        "Un membre choisi n'appartient pas à votre équipe.")
            if not error:
                chef = pool.browse(int(emp_id))
                vals.update({
                    "employee_id": chef.id,
                    "company_id": (chef.company_id
                                   or request.env.company).id,
                })
                mission = request.env["gm.mission"].sudo().create(vals)
                # le chef de mission est déjà membre (auto) ; on ajoute
                # les autres membres cochés
                for mid in membre_ids:
                    if mid != chef.id:
                        request.env["gm.mission.membre"].sudo().create({
                            "mission_id": mission.id, "employee_id": mid})
                self._apply_frais(mission, frais)
                mission.message_post(body=_(
                    "Demande créée par %s (supérieur hiérarchique) via le "
                    "portail.", employees[:1].name))
                if post.get("action") == "submit":
                    try:
                        with self._ecriture_atomique():
                            mission.sudo().action_submit()
                            return request.redirect(
                                "/my/team/missions?success=submitted_for")
                    except (UserError, ValidationError) as exc:
                        mission.frais_ids.sudo().unlink()
                        mission.membre_ids.sudo().unlink()
                        mission.sudo().unlink()
                        error["global"] = exc.args[0] if exc.args else str(exc)
                else:
                    return request.redirect(
                        "/my/team/missions?success=created_for")
            return self._render_mission_form(
                None, self._form_values_from_post(post), error,
                team_mode=True, collaborators=pool,
                selected_employee_id=emp_id,
                selected_membre_ids=membre_ids,
                page_name="team_mission")

        return self._render_mission_form(
            None, self._mission_form_defaults(), {},
            team_mode=True, collaborators=pool,
            selected_employee_id="", selected_membre_ids=[],
            page_name="team_mission")

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
            with self._ecriture_atomique():
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
