# -*- coding: utf-8 -*-
"""Portail employé — mes évaluations (/my/evaluations).

L'agent consulte son évaluation, remplit son auto-évaluation sur la
grille de la campagne, la commente, puis la publie. Tout le reste — qui
peut écrire quoi, quand, et ce qui est visible — est décidé par
``gestion_evaluation`` : le contrôleur ne fait que collecter la saisie
et appeler les méthodes métier.
"""
import html
import re

from odoo import http, _
from odoo.http import request
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from odoo.addons.portal.controllers.portal import pager as portal_pager

import base64

from odoo.addons.portail.controllers.portal_common import (
    PortailCommon,
    validate_justificatif,
)

# Libellés FR des statuts d'une évaluation (hr.appraisal.state)
APPRAISAL_STATE_LABELS = {
    "new": "À confirmer",
    "pending": "En cours",
    "done": "Terminée",
    "cancel": "Annulée",
}

SUCCESS_MESSAGES = {
    "saved": "Votre auto-évaluation a été enregistrée. Vous pourrez la "
             "modifier tant que vous ne l'avez pas publiée.",
    "published": "Votre auto-évaluation a été publiée : votre responsable "
                 "peut désormais la consulter.",
    "noted": "La fiche a été enregistrée : mesure des objectifs et "
             "questions notées. Vous pourrez la modifier tant que vous ne "
             "l'avez pas publiée.",
    "note_published": "Votre notation a été publiée : le collaborateur peut "
                      "désormais la consulter.",
    "validated": "La phase a été validée.",
    "sent_back": "L'évaluation a été renvoyée pour correction.",
    "goal_added": "L'objectif a été ajouté.",
    "goal_removed": "L'objectif a été retiré.",
    "objectif_fixe": "L'objectif a été fixé. Votre collaborateur le voit "
                     "sur son portail.",
    "objectif_retire": "L'objectif a été retiré.",
    "avancement_enregistre": "Votre avancement a été enregistré.",
    "activite_ajoutee": "L'activité a été ajoutée.",
    "activite_retiree": "L'activité a été retirée.",
    "progress_saved": "L'avancement de vos objectifs a été enregistré.",
    "interview_set": "La date de l'entretien a été enregistrée. Le "
                     "collaborateur la voit sur sa fiche.",
    "interview_done": "L'entretien a été déclaré réalisé : l'évaluation est "
                      "clôturée.",
    "report_saved": "Le compte-rendu d'entretien a été déposé. Le service RH "
                    "le retrouve sur la fiche du collaborateur.",
}


class PortailEvaluation(PortailCommon):

    # ------------------------------------------------------------------
    # Accueil /my : carte « Mes évaluations »
    # ------------------------------------------------------------------
    def _my_appraisals_domain(self, employees):
        return [("employee_id", "in", employees.ids)]

    def _team_appraisals_domain(self, employees):
        """Les évaluations que je mène : celles où je suis désigné
        évaluateur, ou acteur d'une phase du circuit."""
        return ["&", ("employee_id", "not in", employees.ids),
                "|", ("manager_ids", "in", employees.ids),
                ("ev_etape_ids.validator_id", "in", employees.ids)]

    def _est_evaluateur(self):
        employees = self._get_portal_employees()
        if not employees:
            return False
        return bool(request.env["hr.appraisal"].sudo().search_count(
            self._team_appraisals_domain(employees)))

    def _ev_periodes_objectifs(self):
        """Les périodes d'objectifs qui concernent MES collaborateurs.

        On ne s'appuie sur aucune évaluation : les objectifs se fixent en
        début d'exercice, des mois avant qu'une campagne n'existe.
        """
        employees = self._get_portal_employees()
        Periode = request.env["ev.periode.objectifs"].sudo()
        if not employees:
            return Periode
        subordonnes = request.env["hr.employee"].sudo().search(
            [("parent_id", "in", employees.ids)])
        if not subordonnes:
            return Periode
        periodes = Periode.search([
            ("state", "in", ("open", "closed")),
            ("company_id", "in", subordonnes.company_id.ids),
        ])
        # Une période dont le ciblage ne retient aucun de mes
        # collaborateurs n'a rien à faire sur mon écran.
        return periodes.filtered(
            lambda p: p._get_employees_cibles() & subordonnes)

    def _est_responsable_objectifs(self):
        return bool(self._ev_periodes_objectifs())

    def _ev_mes_periodes(self):
        """Les périodes au titre desquelles J'AI des objectifs."""
        employees = self._get_portal_employees()
        Periode = request.env["ev.periode.objectifs"].sudo()
        if not employees:
            return Periode
        objectifs = request.env["hr.appraisal.goal"].sudo().search([
            ("employee_id", "in", employees.ids),
            ("ev_periode_id", "!=", False),
        ])
        return objectifs.ev_periode_id

    # La grille avait été coupée le temps de la reprendre : elle portait
    # encore l'ancien contenu (savoir-faire / savoir-être). Elle porte
    # désormais les SECTIONS de la fiche de la banque — conscience
    # professionnelle, management — et reprend donc sa place.
    EV_AFFICHER_GRILLE = True

    def _prepare_portal_layout_values(self):
        values = super()._prepare_portal_layout_values()
        values["afficher_grille"] = self.EV_AFFICHER_GRILLE
        values["portail_is_evaluateur"] = self._est_evaluateur()
        values["portail_has_objectifs"] = self._est_responsable_objectifs()
        return values

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        employees = self._get_portal_employees()
        if "appraisal_count" in counters:
            values["appraisal_count"] = request.env["hr.appraisal"].sudo(
            ).search_count(self._my_appraisals_domain(employees)) \
                if employees else 0
        if "team_appraisal_count" in counters:
            values["team_appraisal_count"] = request.env["hr.appraisal"].sudo(
            ).search_count(self._team_appraisals_domain(employees)) \
                if employees else 0
        if "objectifs_count" in counters:
            # Ce qui compte pour le responsable, ce n'est pas le nombre de
            # périodes : c'est le nombre de collaborateurs qu'il n'a pas
            # encore servis.
            values["objectifs_count"] = sum(
                len(self._ev_collaborateurs_sans_objectif(p))
                for p in self._ev_periodes_objectifs().filtered("ouverte"))
        if "mes_objectifs_count" in counters:
            employees = self._get_portal_employees()
            values["mes_objectifs_count"] = request.env[
                "hr.appraisal.goal"].sudo().search_count([
                    ("employee_id", "in", employees.ids),
                    ("ev_periode_id", "!=", False)]) if employees else 0
        return values

    def _ev_verifier_mon_objectif(self, periode, objectif_id):
        """L'objectif visé appartient-il bien à l'un de MES collaborateurs ?

        Sans ce contrôle, un responsable pourrait viser l'objectif d'un
        agent d'un autre service en trafiquant le formulaire.
        """
        try:
            objectif_id = int(objectif_id or 0)
        except (TypeError, ValueError):
            objectif_id = 0
        objectif = periode.goal_ids.filtered(lambda g: g.id == objectif_id)
        if not objectif or objectif.employee_id not in \
                self._ev_mes_collaborateurs(periode):
            raise UserError(_(
                "Cet objectif ne fait pas partie de ceux de vos "
                "collaborateurs."))
        return objectif

    def _ev_mes_collaborateurs(self, periode):
        """Mes collaborateurs directs visés par cette période."""
        employees = self._get_portal_employees()
        if not employees:
            return request.env["hr.employee"].sudo()
        return periode._get_employees_cibles().filtered(
            lambda e: e.parent_id in employees)

    def _ev_collaborateurs_sans_objectif(self, periode):
        return self._ev_mes_collaborateurs(periode) - periode.goal_ids.employee_id

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_appraisal_or_raise(self, appraisal_id):
        """L'évaluation, après contrôle qu'elle appartient bien à
        l'employé rattaché au compte portail connecté."""
        employees = self._get_portal_employees()
        appraisal = request.env["hr.appraisal"].sudo().browse(
            appraisal_id).exists()
        if not appraisal:
            raise MissingError(_("Cette évaluation n'existe pas."))
        if appraisal.employee_id not in employees:
            raise AccessError(_("Vous n'avez pas accès à cette évaluation."))
        return appraisal

    def _appraisal_user(self, appraisal):
        """L'évaluation telle que la voit l'utilisateur connecté.

        `sudo()` lève les restrictions de LECTURE (un utilisateur portail
        n'a accès ni à hr.employee ni aux tables du circuit) mais ne
        change PAS l'identité : `env.user` reste l'utilisateur connecté,
        et c'est lui que les règles de `gestion_evaluation` évaluent —
        qui peut écrire dans quelle colonne, à quelle phase, et ce qui
        est visible.
        """
        return appraisal.with_user(request.env.user).sudo()

    @staticmethod
    def _html_vers_texte(valeur):
        """Le contenu d'un champ HTML, rendu lisible dans une zone de
        saisie simple : sans balises, un paragraphe par ligne."""
        if not valeur:
            return ""
        texte = re.sub(r"<\s*br\s*/?>", "\n", valeur, flags=re.I)
        texte = re.sub(r"</\s*(p|div|li|h[1-6])\s*>", "\n", texte, flags=re.I)
        texte = re.sub(r"<[^>]+>", "", texte)
        lignes = [l.strip() for l in html.unescape(texte).splitlines()]
        return "\n".join(lignes).strip()

    @staticmethod
    def _texte_vers_html(valeur):
        """L'inverse : ce que l'agent a tapé devient du HTML propre, pour
        que le champ reste exploitable partout (fiche Odoo, export)."""
        texte = (valeur or "").strip()
        if not texte:
            return False
        return "".join(
            "<p>%s</p>" % html.escape(ligne.strip())
            for ligne in texte.splitlines() if ligne.strip())

    def _appraisal_values(self, appraisal, **extra):
        vue = self._appraisal_user(appraisal)
        values = {
            "appraisal": appraisal,
            "vue": vue,
            "state_labels": APPRAISAL_STATE_LABELS,
            # Les zones de saisie du portail sont du texte simple : on
            # convertit dans les deux sens plutôt que d'afficher des
            # balises à l'utilisateur.
            "employee_feedback_texte": self._html_vers_texte(
                appraisal.employee_feedback),
            "manager_feedback_texte": self._html_vers_texte(
                appraisal.manager_feedback),
            "page_name": "appraisal",
            # Valeurs par défaut : un gabarit qui lit une clé absente
            # échoue. Chaque écran ne remplit que ce qui le concerne.
            "error": {},
            "motif_objectifs": None,
            "motif_avancement": None,
            "motif_notation": None,
            "progressions": [],
            # La partie grille est mise de côté : le drapeau la rallume
            # sur les trois écrans à la fois.
            "afficher_grille": self.EV_AFFICHER_GRILLE,
        }
        values.update(extra)
        return values

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------
    @http.route(["/my/evaluations", "/my/evaluations/page/<int:page>"],
                type="http", auth="user", website=True)
    def portal_my_appraisals(self, page=1, **kw):
        employees = self._get_portal_employees()
        Appraisal = request.env["hr.appraisal"].sudo()
        domain = self._my_appraisals_domain(employees)

        total = Appraisal.search_count(domain)
        pager = portal_pager(url="/my/evaluations", total=total, page=page,
                             step=self._items_per_page)
        appraisals = Appraisal.search(
            domain, order="date_close desc, id desc",
            limit=self._items_per_page, offset=pager["offset"])

        values = {
            "appraisals": appraisals,
            "state_labels": APPRAISAL_STATE_LABELS,
            "success_message": SUCCESS_MESSAGES.get(kw.get("success")),
            "page_name": "appraisal",
            "pager": pager,
            "default_url": "/my/evaluations",
        }
        return request.render(
            "portail_evaluation.portal_my_appraisals", values)

    @http.route(["/my/evaluations/<int:appraisal_id>"],
                type="http", auth="user", website=True,
                methods=["GET", "POST"])
    def portal_my_appraisal_detail(self, appraisal_id=None, **post):
        """Sa fiche : ce qu'il a reçu comme objectifs, où il en est, et sa
        notation quand elle est visible. L'avancement des objectifs se
        déclare ici, tout au long de l'exercice."""
        try:
            appraisal = self._get_appraisal_or_raise(appraisal_id)
        except (AccessError, MissingError):
            return request.redirect("/my/evaluations")
        vue = self._appraisal_user(appraisal)
        error = {}

        if request.httprequest.method == "POST":
            try:
                with self._ecriture_atomique():
                    if post.get("action") != "progress_save":
                        raise UserError(_("Action inconnue."))
                    # Une case par objectif : « progress_<id> ».
                    vue._ev_objectif_avancement({
                        cle[len("progress_"):]: valeur
                        for cle, valeur in post.items()
                        if cle.startswith("progress_")})
                    return request.redirect(
                        "/my/evaluations/%s?success=progress_saved" % appraisal.id)
            except (UserError, ValidationError) as exc:
                error["global"] = exc.args[0] if exc.args else str(exc)

        return request.render(
            "portail_evaluation.portal_my_appraisal_detail",
            self._appraisal_values(
                appraisal, error=error,
                motif_avancement=vue._ev_motif_avancement_ferme(),
                progressions=request.env["hr.appraisal.goal"]._fields[
                    "progression"].selection,
                success_message=SUCCESS_MESSAGES.get(post.get("success"))))

    @http.route(["/my/evaluations/<int:appraisal_id>/auto-evaluation"],
                type="http", auth="user", website=True,
                methods=["GET", "POST"])
    def portal_my_appraisal_auto(self, appraisal_id=None, **post):
        """Saisie de l'auto-évaluation : une appréciation par critère,
        plus le commentaire. « Enregistrer » laisse modifiable,
        « Publier » transmet au responsable et fige."""
        try:
            appraisal = self._get_appraisal_or_raise(appraisal_id)
        except (AccessError, MissingError):
            return request.redirect("/my/evaluations")
        vue = self._appraisal_user(appraisal)
        if not vue.ev_auto_modifiable:
            return request.redirect("/my/evaluations/%s" % appraisal.id)

        error = {}
        if request.httprequest.method == "POST":
            try:
                # Même règle que côté responsable : ce qui est saisi
                # est enregistré, même si la publication est refusée.
                with self._ecriture_atomique():
                    self._enregistrer_auto(appraisal, post)
                if post.get("action") != "publish":
                    return request.redirect(
                        "/my/evaluations/%s/auto-evaluation?success=saved"
                        % appraisal.id)
                try:
                    with self._ecriture_atomique():
                        vue.action_ev_publier_auto()
                except (UserError, ValidationError) as refus:
                    raise UserError(_(
                        "%(motif)s Votre saisie, elle, est bien "
                        "enregistrée : rien n'est perdu.",
                        motif=(refus.args[0] if refus.args else str(refus))))
                return request.redirect(
                    "/my/evaluations/%s?success=published" % appraisal.id)
            except (UserError, ValidationError) as exc:
                error["global"] = exc.args[0] if exc.args else str(exc)

        return request.render(
            "portail_evaluation.portal_my_appraisal_auto",
            self._appraisal_values(
                appraisal, error=error,
                niveaux=appraisal.ev_niveau_ids,
                success_message=SUCCESS_MESSAGES.get(post.get("success"))))

    # ------------------------------------------------------------------
    # Espace évaluateur : les évaluations que je mène
    # ------------------------------------------------------------------
    def _get_team_appraisal_or_raise(self, appraisal_id):
        employees = self._get_portal_employees()
        appraisal = request.env["hr.appraisal"].sudo().browse(
            appraisal_id).exists()
        if not appraisal:
            raise MissingError(_("Cette évaluation n'existe pas."))
        concerne = (
            (appraisal.manager_ids & employees)
            or (appraisal.ev_etape_ids.validator_id & employees))
        if not concerne or appraisal.employee_id in employees:
            raise AccessError(_(
                "Vous n'êtes pas évaluateur de cette évaluation."))
        return appraisal

    # ------------------------------------------------------------------
    # Fixation des objectifs — sans aucune évaluation
    # ------------------------------------------------------------------
    @http.route(["/my/mes-objectifs"], type="http", auth="user",
                website=True, methods=["GET", "POST"])
    def portal_mes_objectifs_agent(self, **post):
        """Ce que l'agent voit : la commande qu'on lui a passée pour
        l'exercice, et où il en est.

        Sans cet écran, un objectif fixé en janvier restait invisible
        jusqu'à l'ouverture de la campagne, en fin d'année.
        """
        periodes = self._ev_mes_periodes()
        if not periodes:
            return request.redirect("/my")
        employees = self._get_portal_employees()
        moi = employees[:1]
        error = {}
        success = None

        if request.httprequest.method == "POST":
            periode = periodes.filtered(
                lambda p: str(p.id) == (post.get("periode_id") or ""))
            if not periode:
                error["global"] = _("Période inconnue.")
            else:
                try:
                    with self._ecriture_atomique():
                        periode._ev_objectif_avancement(moi, post)
                        return request.redirect(
                            "/my/mes-objectifs?success=avancement_enregistre")
                except (UserError, ValidationError) as exc:
                    error["global"] = exc.args[0] if exc.args else str(exc)

        if post.get("success"):
            success = SUCCESS_MESSAGES.get(post["success"])

        lignes = [{
            "periode": periode,
            "objectifs": periode._ev_objectifs_de(moi),
        } for periode in periodes.sorted("exercice", reverse=True)]

        return request.render(
            "portail_evaluation.portal_mes_objectifs_agent", {
                "lignes": lignes,
                "niveaux": request.env["hr.appraisal.goal"]
                ._fields["progression"].selection,
                "error": error,
                "success_message": success,
                "page_name": "mes_objectifs",
            })

    @http.route(["/my/objectifs"], type="http", auth="user",
                website=True)
    def portal_objectifs_exercices(self, **post):
        """Niveau 1 — les exercices. Une ligne par période ouverte par la
        RH, avec l'avancement du responsable sur chacune."""
        periodes = self._ev_periodes_objectifs()
        if not periodes:
            return request.redirect("/my")
        lignes = [{
            "periode": periode,
            "agents": len(self._ev_mes_collaborateurs(periode)),
            "sans_objectif": len(
                self._ev_collaborateurs_sans_objectif(periode)),
        } for periode in periodes.sorted(
            lambda p: (p.state != "open", p.exercice), reverse=False)]
        return request.render(
            "portail_evaluation.portal_objectifs_exercices", {
                "lignes": lignes,
                "success_message": SUCCESS_MESSAGES.get(post.get("success")),
                "page_name": "objectifs",
            })

    def _ev_periode_ou_rediriger(self, periode_id):
        """La période, si elle concerne bien mes collaborateurs."""
        periode = self._ev_periodes_objectifs().filtered(
            lambda p: p.id == periode_id)
        if not periode:
            raise MissingError(_("Cette période ne vous concerne pas."))
        return periode

    @http.route(["/my/objectifs/<int:periode_id>"], type="http",
                auth="user", website=True)
    def portal_objectifs_collaborateurs(self, periode_id=None, **post):
        """Niveau 2 — mes collaborateurs pour cette période, et où en est
        chacun d'eux."""
        try:
            periode = self._ev_periode_ou_rediriger(periode_id)
        except (AccessError, MissingError):
            return request.redirect("/my/objectifs")
        agents = []
        for agent in self._ev_mes_collaborateurs(periode).sorted("name"):
            objectifs = periode._ev_objectifs_de(agent)
            agents.append({
                "employee": agent,
                "nb_objectifs": len(objectifs),
                "nb_activites": sum(o.ev_nb_activites for o in objectifs),
                # Ce qui doit sauter aux yeux : un objectif sans activité
                # ne pourra pas être noté en fin d'exercice.
                "objectifs_sans_activite": len(
                    objectifs.filtered(lambda o: not o.ev_activite_ids)),
            })
        return request.render(
            "portail_evaluation.portal_objectifs_collaborateurs", {
                "periode": periode,
                "motif_ferme": periode._ev_motif_saisie_responsable(),
                "agents": agents,
                "success_message": SUCCESS_MESSAGES.get(post.get("success")),
                "page_name": "objectifs",
            })

    @http.route(["/my/objectifs/<int:periode_id>/<int:employee_id>"],
                type="http", auth="user", website=True,
                methods=["GET", "POST"])
    def portal_objectifs_agent(self, periode_id=None, employee_id=None,
                               **post):
        """Niveau 3 — les objectifs d'UN collaborateur, leurs activités et
        les résultats attendus. Toute la saisie se fait ici."""
        try:
            periode = self._ev_periode_ou_rediriger(periode_id)
        except (AccessError, MissingError):
            return request.redirect("/my/objectifs")
        agent = self._ev_mes_collaborateurs(periode).filtered(
            lambda e: e.id == employee_id)
        if not agent:
            return request.redirect("/my/objectifs/%s" % periode.id)
        retour = "/my/objectifs/%s/%s" % (periode.id, agent.id)
        error = {}

        if request.httprequest.method == "POST":
            try:
                with self._ecriture_atomique():
                    # La banque peut avoir décidé que la RH tient la
                    # plume pour cet exercice : le responsable consulte
                    # seulement.
                    periode._ev_check_saisie_responsable()
                    action = post.get("action")
                    if action == "goal_add":
                        # Le responsable qui passe la commande, c'est
                        # l'utilisateur connecté — pas forcément le supérieur
                        # enregistré sur la fiche.
                        moi = self._get_portal_employees()[:1]
                        periode._ev_objectif_creer(
                            agent, post.get("goal_name"),
                            echeance=(post.get("goal_deadline") or "").strip()
                            or None,
                            description=self._texte_vers_html(
                                post.get("goal_description")),
                            manager=agent.parent_id or moi)
                        return request.redirect(retour + "?success=objectif_fixe")
                    if action == "goal_remove":
                        self._ev_verifier_mon_objectif(periode,
                                                       post.get("goal_id"))
                        periode._ev_objectif_supprimer(post.get("goal_id"))
                        return request.redirect(
                            retour + "?success=objectif_retire")
                    if action == "activite_add":
                        self._ev_verifier_mon_objectif(periode,
                                                       post.get("goal_id"))
                        periode._ev_activite_creer(
                            post.get("goal_id"), post.get("activite_name"),
                            resultat_attendu=post.get("resultat_attendu"))
                        return request.redirect(
                            retour + "?success=activite_ajoutee")
                    if action == "activite_remove":
                        periode._ev_activite_supprimer(post.get("activite_id"))
                        return request.redirect(
                            retour + "?success=activite_retiree")
                    if action == "goals_duplicate":
                        # Les cases cochées arrivent en plusieurs valeurs
                        # sous le même nom : `post` n'en garde qu'une,
                        # d'où la lecture directe du formulaire.
                        ids = request.httprequest.form.getlist("cible_ids")
                        cibles = self._ev_mes_collaborateurs(periode).filtered(
                            lambda e: str(e.id) in ids)
                        if not cibles:
                            raise UserError(_(
                                "Choisissez au moins un collaborateur vers "
                                "qui recopier ces objectifs."))
                        moi = self._get_portal_employees()[:1]
                        bilan = periode._ev_objectifs_dupliquer(
                            agent, cibles, manager=moi)
                        return request.redirect(
                            "%s?success=objectifs_dupliques&copies=%s"
                            "&agents=%s&ignores=%s"
                            % (retour, bilan["copies"], bilan["agents"],
                               len(bilan["ignores"])))
            except (UserError, ValidationError) as exc:
                error["global"] = exc.args[0] if exc.args else str(exc)

        return request.render("portail_evaluation.portal_objectifs_agent", {
            "periode": periode,
            # Le motif couvre les deux cas : période fermée, ou saisie
            # réservée à la RH.
            "motif_ferme": periode._ev_motif_saisie_responsable(),
            "saisie_ouverte": not periode._ev_motif_saisie_responsable(),
            "agent": agent,
            "objectifs": periode._ev_objectifs_de(agent),
            # Vers qui recopier : mes autres collaborateurs de la période,
            # avec ce qu'ils ont déjà — recopier vers quelqu'un qui a déjà
            # ses objectifs n'est pas la même décision.
            "autres_agents": [
                (autre, len(periode._ev_objectifs_de(autre)))
                for autre in self._ev_mes_collaborateurs(periode) - agent
            ],
            "error": error,
            "success_message": self._ev_message_duplication(post)
            or SUCCESS_MESSAGES.get(post.get("success")),
            "page_name": "objectifs",
        })

    def _ev_message_duplication(self, post):
        """Le compte rendu d'une duplication, chiffres à l'appui.

        « Enregistré » ne suffit pas ici : le responsable doit savoir
        combien d'objectifs sont partis, vers combien d'agents, et
        combien ont été laissés de côté parce qu'ils y étaient déjà.
        """
        if post.get("success") != "objectifs_dupliques":
            return None

        def entier(cle):
            try:
                return int(post.get(cle) or 0)
            except (TypeError, ValueError):
                return 0

        copies, agents, ignores = (entier("copies"), entier("agents"),
                                   entier("ignores"))
        message = _(
            "%(copies)s objectif(s) recopié(s) vers %(agents)s "
            "collaborateur(s).", copies=copies, agents=agents)
        if ignores:
            message += " " + _(
                "%s objectif(s) y figuraient déjà : ils n'ont pas été "
                "recopiés.", ignores)
        return message

    @http.route(["/my/team/evaluations",
                 "/my/team/evaluations/page/<int:page>"],
                type="http", auth="user", website=True)
    def portal_team_appraisals(self, page=1, **kw):
        employees = self._get_portal_employees()
        Appraisal = request.env["hr.appraisal"].sudo()
        domain = self._team_appraisals_domain(employees)

        # « En attente de mon action » couvre DEUX cas : la phase en cours
        # m'attend, ou ma notation est ouverte sans que ce soit encore mon
        # tour — la saisie est possible par anticipation, l'évaluateur doit
        # donc trouver ces dossiers sans avoir à les chercher.
        ouvertes = Appraisal.search(
            domain + [("state", "not in", ("done", "cancel"))],
            order="id desc")
        a_traiter = ouvertes.filtered(
            lambda a: a.ev_acteur_courant_id in employees
            or self._appraisal_user(a).ev_notation_modifiable)
        reste = domain + [("id", "not in", a_traiter.ids)]
        total = Appraisal.search_count(reste)
        pager = portal_pager(url="/my/team/evaluations", total=total,
                             page=page, step=self._items_per_page)
        autres = Appraisal.search(
            reste, order="id desc", limit=self._items_per_page,
            offset=pager["offset"])

        values = {
            "a_traiter": a_traiter,
            "autres": autres,
            "state_labels": APPRAISAL_STATE_LABELS,
            "success_message": SUCCESS_MESSAGES.get(kw.get("success")),
            "page_name": "team_appraisal",
            "pager": pager,
            "default_url": "/my/team/evaluations",
        }
        return request.render(
            "portail_evaluation.portal_team_appraisals", values)

    @http.route(["/my/team/evaluations/<int:appraisal_id>"],
                type="http", auth="user", website=True,
                methods=["GET", "POST"])
    def portal_team_appraisal_detail(self, appraisal_id=None, **post):
        """Écran de l'évaluateur : il note, commente, publie, puis valide
        sa phase (ou la renvoie pour correction)."""
        try:
            appraisal = self._get_team_appraisal_or_raise(appraisal_id)
        except (AccessError, MissingError):
            return request.redirect("/my/team/evaluations")
        vue = self._appraisal_user(appraisal)
        error = {}

        if request.httprequest.method == "POST":
            action = post.get("action")
            commentaire = (post.get("comment") or "").strip() or None
            try:
                if action in ("save", "publish"):
                    # La saisie s'enregistre pour elle-même. Publier est
                    # une décision SÉPARÉE : si elle est refusée — une
                    # fiche encore incomplète, par exemple — ce qui vient
                    # d'être saisi reste en base. Les enchaîner dans le
                    # même point de reprise faisait tout perdre.
                    with self._ecriture_atomique():
                        vue._ev_mesurer(post)
                        self._enregistrer_notation(appraisal, post)
                    if action != "publish":
                        return request.redirect(
                            "/my/team/evaluations/%s?success=noted"
                            % appraisal.id)
                    try:
                        with self._ecriture_atomique():
                            vue.action_ev_publier_notation()
                    except (UserError, ValidationError) as refus:
                        raise UserError(_(
                            "%(motif)s Votre saisie, elle, est bien "
                            "enregistrée : rien n'est perdu.",
                            motif=(refus.args[0] if refus.args
                                   else str(refus))))
                    return request.redirect(
                        "/my/team/evaluations/%s?success=note_published"
                        % appraisal.id)
                with self._ecriture_atomique():
                    if action == "goal_add":
                        vue._ev_objectif_creer(
                            post.get("goal_name"),
                            echeance=(post.get("goal_deadline") or "").strip()
                            or None,
                            description=self._texte_vers_html(
                                post.get("goal_description")))
                        return request.redirect(
                            "/my/team/evaluations/%s?success=goal_added"
                            % appraisal.id)
                    if action == "goal_remove":
                        vue._ev_objectif_supprimer(post.get("goal_id"))
                        return request.redirect(
                            "/my/team/evaluations/%s?success=goal_removed"
                            % appraisal.id)
                    if action == "interview_set":
                        vue._ev_fixer_entretien(
                            post.get("date_entretien"),
                            heure_entretien=(post.get("heure_entretien")
                                             or "").strip() or None)
                        return request.redirect(
                            "/my/team/evaluations/%s?success=interview_set"
                            % appraisal.id)
                    if action == "report_add":
                        fichier = request.httprequest.files.get(
                            "compte_rendu")
                        contenu = fichier.read() if fichier else b""
                        if not contenu:
                            raise ValidationError(_(
                                "Choisissez un fichier à déposer."))
                        validate_justificatif(fichier.filename, contenu)
                        vue._ev_deposer_compte_rendu(
                            base64.b64encode(contenu), fichier.filename)
                        return request.redirect(
                            "/my/team/evaluations/%s?success=report_saved"
                            % appraisal.id)
                    if action == "validate":
                        entretien = vue.ev_entretien_modifiable
                        vue.action_ev_valider_etape(comment=commentaire)
                        return request.redirect(
                            "/my/team/evaluations?success=%s"
                            % ("interview_done" if entretien else "validated"))
                    if action == "send_back":
                        vue.action_ev_renvoyer(comment=commentaire)
                        return request.redirect(
                            "/my/team/evaluations?success=sent_back")
                    raise UserError(_("Action inconnue."))
            except (UserError, ValidationError) as exc:
                error["global"] = exc.args[0] if exc.args else str(exc)

        return request.render(
            "portail_evaluation.portal_team_appraisal_detail",
            self._appraisal_values(
                appraisal, error=error, is_evaluateur=True,
                niveaux=appraisal.ev_niveau_ids,
                # Quand les objectifs sont fermés, on dit POURQUOI plutôt
                # que de faire disparaître la section sans explication.
                motif_objectifs=vue._ev_motif_objectifs_fermes(),
                # Même chose pour la grille : une grille grisée sans un mot
                # d'explication, c'est un appel au support assuré.
                motif_notation=vue._ev_motif_notation_fermee(
                    colonne="manager"),
                success_message=SUCCESS_MESSAGES.get(post.get("success"))))

    def _enregistrer_notation(self, appraisal, post):
        """Reporte la notation du manager. Écriture avec l'utilisateur
        courant : les verrous du module métier s'appliquent."""
        niveaux_valides = set(
            appraisal.ev_niveau_ids.ids)
        for ligne in appraisal.ev_note_ids:
            # Deux façons de noter, selon la grille : un NIVEAU choisi dans
            # l'échelle, ou des POINTS attribués sur ce que vaut le critère.
            if ligne.mode_notation == "points":
                brut = (post.get("points_%s" % ligne.id) or "").strip()
                if not brut:
                    continue
                brut = brut.replace(",", ".")
                try:
                    valeur = float(brut)
                except ValueError:
                    raise ValidationError(_(
                        "Note invalide pour « %(critere)s » : « %(val)s ». "
                        "Attendu un nombre entre 0 et %(max)s.",
                        critere=ligne.critere_id.name or "", val=brut,
                        max=("%g" % ligne.points_max)))
                ligne.with_user(request.env.user).sudo().write(
                    {"valeur_manager": valeur})
                continue
            brut = (post.get("critere_%s" % ligne.id) or "").strip()
            if not brut:
                continue
            if not brut.isdigit() or int(brut) not in niveaux_valides:
                raise ValidationError(_(
                    "Appréciation invalide pour « %s ».",
                    ligne.critere_id.name))
            ligne.with_user(request.env.user).sudo().write(
                {"niveau_manager_id": int(brut)})
        commentaire = post.get("manager_feedback")
        if commentaire is not None:
            appraisal.with_user(request.env.user).sudo().write(
                {"manager_feedback": self._texte_vers_html(commentaire)})

    def _enregistrer_auto(self, appraisal, post):
        """Reporte la saisie du formulaire sur les lignes de notation.

        L'écriture passe par l'utilisateur courant (jamais en sudo) :
        c'est le module métier qui vérifie que l'agent a le droit
        d'écrire dans SA colonne, à ce moment du circuit.
        """
        niveaux_valides = set(
            appraisal.ev_niveau_ids.ids)
        for ligne in appraisal.ev_note_ids:
            brut = (post.get("critere_%s" % ligne.id) or "").strip()
            if not brut:
                continue
            if not brut.isdigit() or int(brut) not in niveaux_valides:
                raise ValidationError(_(
                    "Appréciation invalide pour « %s ».",
                    ligne.critere_id.name))
            ligne.with_user(request.env.user).sudo().write(
                {"niveau_agent_id": int(brut)})
        commentaire = post.get("employee_feedback")
        if commentaire is not None:
            appraisal.with_user(request.env.user).sudo().write(
                {"employee_feedback": self._texte_vers_html(commentaire)})
