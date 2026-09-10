# -*- coding: utf-8 -*-
"""Rattachement à la campagne, et circuit de validation à plusieurs phases.

Le module ne modifie AUCUN comportement natif de ``hr.appraisal`` : les
feedbacks, la notation, les compétences, l'entretien et le 360° restent ceux
d'Odoo. Il ajoute par-dessus le circuit que le standard n'a pas — notamment
la **validation N+2** exigée par le TDR.
"""
from datetime import datetime, time, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class HrAppraisal(models.Model):
    _inherit = "hr.appraisal"

    ev_campagne_id = fields.Many2one(
        "ev.campagne", string="Campagne d'évaluation",
        index=True, copy=False,
        # La campagne peut disparaître, l'évaluation reste : c'est une pièce
        # du dossier de l'agent.
        ondelete="set null",
        help="Campagne annuelle qui a généré cette évaluation. Vide pour "
             "une évaluation créée à l'unité, hors campagne.")

    # ------------------------------------------------------------------
    # Circuit de validation (photo prise au lancement de la campagne)
    # ------------------------------------------------------------------
    ev_etape_ids = fields.One2many(
        "ev.evaluation.etape", "appraisal_id", string="Circuit d'évaluation",
        readonly=True, copy=False)
    ev_phase_courante_id = fields.Many2one(
        "ev.evaluation.etape", string="Phase en cours",
        compute="_compute_ev_phase_courante", store=True)
    ev_acteur_courant_id = fields.Many2one(
        "hr.employee", string="En attente de",
        compute="_compute_ev_phase_courante", store=True,
        help="Personne attendue à la phase en cours. Vide si la phase est "
             "confiée au service RH.")
    ev_can_agir = fields.Boolean(
        compute="_compute_ev_can_agir",
        help="L'utilisateur courant peut-il traiter la phase en cours ?")
    ev_circuit_en_cours = fields.Boolean(
        string="Circuit en cours", compute="_compute_ev_circuit_en_cours",
        store=True,
        help="Vrai tant qu'une phase du circuit reste à jouer. Tant qu'il "
             "l'est, l'évaluation ne peut pas être clôturée directement.")

    # ------------------------------------------------------------------
    # Notation : la grille et ses lignes
    # ------------------------------------------------------------------
    ev_grille_id = fields.Many2one(
        "ev.grille", string="Grille d'évaluation", copy=False,
        ondelete="restrict",
        help="Grille utilisée pour noter cette évaluation. Posée au "
             "lancement de la campagne.")
    ev_note_ids = fields.One2many(
        "ev.notation.ligne", "appraisal_id", string="Notation", copy=False)
    ev_note_globale = fields.Float(
        string="Note du manager", compute="_compute_ev_notation", store=True,
        group_operator="avg",
        help="La note officielle : moyenne des blocs de la grille, telle "
             "que le manager l'a remplie.")
    ev_note_agent = fields.Float(
        string="Auto-évaluation", compute="_compute_ev_notation", store=True,
        group_operator="avg",
        help="Même calcul, sur les notes que l'agent s'est données. Point "
             "de comparaison, jamais la note officielle.")
    ev_ecart_note = fields.Float(
        string="Écart", compute="_compute_ev_notation", store=True,
        help="Note du manager moins auto-évaluation.")

    # --- La note arrêtée le jour de la clôture ---------------------------
    # Les notes ci-dessus se recalculent à partir de la STRUCTURE VIVE de
    # la grille : un critère déplacé d'un thème à l'autre change les
    # moyennes. C'est voulu tant que l'évaluation est ouverte — la fiche
    # affichée et la fiche imprimée doivent dire la même chose.
    #
    # Mais une évaluation CLÔTURÉE est une pièce du dossier de l'agent.
    # Sans ces trois champs, retoucher la grille pour l'exercice suivant
    # réécrivait les notes des exercices passés, en silence et sans
    # trace. On archive donc la note à la clôture, et le calcul la
    # restitue telle quelle tant que l'évaluation reste close.
    ev_note_figee = fields.Boolean(
        string="Note arrêtée", copy=False, readonly=True,
        help="Posé à la clôture. Tant qu'il est vrai, la note ne se "
             "recalcule plus : c'est celle de l'exercice écoulé.")
    ev_note_globale_figee = fields.Float(
        string="Note du manager (arrêtée)", copy=False, readonly=True)
    ev_note_agent_figee = fields.Float(
        string="Auto-évaluation (arrêtée)", copy=False, readonly=True)
    ev_ecart_note_figee = fields.Float(
        string="Écart (arrêté)", copy=False, readonly=True)
    ev_nb_criteres = fields.Integer(
        string="Critères", compute="_compute_ev_notation", store=True)
    ev_nb_notes = fields.Integer(
        string="Critères notés", compute="_compute_ev_notation", store=True)
    ev_nb_notes_agent = fields.Integer(
        string="Critères auto-évalués", compute="_compute_ev_notation",
        store=True)
    ev_notation_complete = fields.Boolean(
        string="Notation complète", compute="_compute_ev_notation",
        store=True)
    ev_agent_complete = fields.Boolean(
        string="Auto-évaluation complète", compute="_compute_ev_notation",
        store=True)
    ev_notation_detail = fields.Html(
        string="Détail de la notation", compute="_compute_ev_detail",
        sanitize=False)
    ev_notation_modifiable = fields.Boolean(
        string="Notation ouverte", compute="_compute_ev_notation_modifiable",
        help="L'utilisateur courant peut-il saisir la note du manager ?")
    ev_auto_modifiable = fields.Boolean(
        string="Auto-évaluation ouverte",
        compute="_compute_ev_notation_modifiable",
        help="L'utilisateur courant peut-il saisir son auto-évaluation ?")
    ev_auto_evaluation_active = fields.Boolean(
        string="Auto-évaluation prévue", compute="_compute_ev_auto_active",
        store=True,
        help="Faux quand le service RH a désactivé l'auto-évaluation : "
             "l'agent ne remplit aucune grille, seule la notation du "
             "responsable compte. Photographié au lancement de la "
             "campagne, comme le reste du circuit.")
    ev_voir_notes_agent = fields.Boolean(
        string="Voir l'auto-évaluation", compute="_compute_ev_visibilite",
        help="L'auto-évaluation n'est visible des autres qu'une fois "
             "publiée par l'agent.")
    ev_voir_notes_manager = fields.Boolean(
        string="Voir la note du manager", compute="_compute_ev_visibilite",
        help="La note du manager n'est visible de l'agent qu'une fois "
             "publiée.")

    # ------------------------------------------------------------------
    # Qui peut noter, et quand
    # ------------------------------------------------------------------
    @api.model
    def _ev_employes_utilisateur(self):
        """Les fiches employé de l'utilisateur courant.

        DEUX rattachements coexistent et doivent tous deux fonctionner :
        * « Utilisateur associé » (``user_id``), le lien standard d'Odoo,
          posé quand on crée un utilisateur interne ;
        * le **contact professionnel** (``work_contact_id``), le lien
          qu'utilise le module ``portail`` lorsqu'il provisionne un accès
          portail à un agent.
        Sans le second, un agent connecté au portail n'était pas reconnu
        comme l'évalué, et aucun bouton ne s'affichait.
        Lecture en sudo : un utilisateur portail n'a pas le droit de lire
        hr.employee, mais il doit pouvoir se reconnaître lui-même.
        """
        user = self.env.user
        Employee = self.env["hr.employee"].sudo()
        domaine = [("user_id", "=", user.id)]
        if user.partner_id:
            domaine = ["|"] + domaine + [
                ("work_contact_id", "=", user.partner_id.id)]
        return Employee.search(domaine)

    def _ev_est_agent(self):
        """L'utilisateur courant est-il l'agent évalué ?"""
        self.ensure_one()
        employee = self.sudo().employee_id
        return bool(employee and employee in self._ev_employes_utilisateur())

    def _compute_buttons_display(self):
        """Faire reconnaître par Odoo l'agent connecté au portail.

        Odoo ne connaît qu'un seul rattachement employé↔utilisateur,
        ``self.env.user.employee_id``. Ce champ est VIDE pour nos agents
        du portail : le module ``portail`` les rattache par le contact
        professionnel (``work_contact_id``). Odoo prenait donc l'agent
        pour un gestionnaire tiers et refusait sa propre auto-évaluation
        — « Les feedbacks des employés ne peuvent pas être modifiés par
        les gestionnaires » (hr_appraisal, ``_check_access``).

        On ne touche ni aux données ni au code d'Odoo : on complète son
        calcul avec la seconde convention. On n'ajoute de droit qu'à
        celui qui est réellement l'agent évalué, ou réellement inscrit
        parmi les évaluateurs — on n'en retire jamais. Les verrous
        métier (phase, publication, clôture) restent entièrement du
        ressort de ``_ev_motif_notation_fermee``.
        """
        super()._compute_buttons_display()
        mes_employes = self._ev_employes_utilisateur()
        if not mes_employes:
            return
        for appraisal in self:
            # sudo() sur les LECTURES : un utilisateur portail n'a pas le
            # droit de lire hr.employee. L'identité reste la sienne.
            fiche = appraisal.sudo()
            if fiche.employee_id and fiche.employee_id in mes_employes:
                appraisal.can_see_employee_publish = True
            if fiche.manager_ids & mes_employes:
                appraisal.can_see_manager_publish = True

    def _ev_motif_notation_fermee(self, colonne="manager"):
        """None si la saisie est ouverte à l'utilisateur courant sur la
        colonne demandée, sinon le motif du refus, rédigé pour être lu.

        ``colonne`` : « agent » (auto-évaluation), « manager » (la note
        officielle) ou « mixte » (les deux à la fois — jamais autorisé).

        Les verrous, dans cet ordre :
        1. une évaluation close ou annulée est figée pour tout le monde ;
        2. une colonne PUBLIÉE ne se retouche plus, même par son auteur ;
        3. le service RH peut corriger tant que l'évaluation est ouverte ;
        4. chacun ne remplit que SA colonne, pendant la phase qui lui
           revient, et seulement si cette phase donne accès à la grille.
        """
        self.ensure_one()
        if colonne == "mixte":
            return _(
                "Auto-évaluation et note du manager ne se saisissent pas "
                "ensemble : chacun remplit sa propre colonne.")
        if self.state == "done":
            return _(
                "L'évaluation de %s est clôturée : la notation est figée et "
                "ne peut plus être modifiée. Le service RH doit d'abord la "
                "rouvrir s'il faut corriger une erreur.",
                self.sudo().employee_id.name or "")
        if self.state == "cancel":
            return _(
                "L'évaluation de %s est annulée : sa notation ne se modifie "
                "plus.", self.sudo().employee_id.name or "")

        publiee = (self.employee_feedback_published if colonne == "agent"
                   else self.manager_feedback_published)
        est_rh = self.env.user.has_group(
            "hr_appraisal.group_hr_appraisal_user")
        if publiee and not est_rh:
            return _(
                "Cette partie est publiée : elle ne se modifie plus. "
                "Demandez au service RH s'il faut corriger une erreur.")
        if est_rh:
            return None
        # Tant que la campagne en est à la fixation des objectifs, personne
        # ne note : on est en début d'exercice, il n'y a rien à évaluer.
        # Sans ce verrou, la saisie par anticipation (§14) laisserait un
        # responsable noter l'année dès le mois de janvier.
        campagne = self.sudo().ev_campagne_id
        if campagne and campagne.state == "draft":
            return _(
                "La campagne « %s » n'est pas encore lancée : il n'y a "
                "rien à noter.", campagne.name or "")
        if colonne == "agent" and not self._ev_est_agent():
            return _(
                "L'auto-évaluation appartient à %s : vous ne pouvez pas la "
                "remplir à sa place.", self.sudo().employee_id.name or "")
        if colonne == "manager" and self._ev_est_agent():
            return _(
                "La note du manager ne se saisit pas par l'agent évalué. "
                "Remplissez votre auto-évaluation.")
        # La colonne s'ouvre à son propriétaire dès que l'évaluation est en
        # route, SANS attendre son tour dans le circuit. Les deux notations
        # sont indépendantes par construction — chacun note de son côté,
        # l'auto-évaluation ne sert au responsable qu'en comparaison, à
        # l'entretien. Faire attendre le responsable bloquait toute une
        # campagne dès qu'un agent était en congé ou en mission.
        #
        # Les VALIDATIONS, elles, restent séquentielles : on ne valide pas
        # sa phase avant son tour, et le N+2 statue toujours après.
        etape = self._ev_etape_de_notation(colonne)
        if not etape:
            return _(
                "Aucune phase du circuit ne donne accès à la grille de "
                "notation pour vous sur cette évaluation : seul le service "
                "RH peut intervenir.")
        if etape.state == "skipped":
            return _(
                "La phase « %(phase)s » a été écartée du circuit au "
                "lancement de la campagne : %(motif)s.",
                phase=etape.name,
                motif=etape.skip_reason or _("elle ne pouvait pas être jouée"))
        if etape.state == "done":
            return _(
                "La phase « %(phase)s » est déjà traitée : sa notation ne "
                "se reprend plus. Demandez au service RH s'il faut corriger "
                "une erreur.", phase=etape.name)
        return None

    def _ev_etape_de_notation(self, colonne):
        """L'étape du circuit qui porte la colonne demandée, POUR
        l'utilisateur courant.

        La colonne « agent » est celle de l'évalué ; la colonne
        « manager » celle de l'évaluateur. On retient la première étape
        non traitée qui donne accès à la grille et dont l'utilisateur est
        l'acteur attendu — que ce soit son tour ou non.
        """
        self.ensure_one()
        fiche = self.sudo()
        mes_employes = self._ev_employes_utilisateur()
        candidates = fiche.ev_etape_ids.filtered(
            lambda e: e.saisie_notation and e.validator_id in mes_employes)
        if colonne == "agent":
            candidates = candidates.filtered(
                lambda e: e.validator_id == fiche.employee_id)
        else:
            candidates = candidates.filtered(
                lambda e: e.validator_id != fiche.employee_id)
        ouvertes = candidates.filtered(
            lambda e: e.state not in ("done", "skipped"))
        return (ouvertes or candidates)[:1]

    @api.depends_context("uid")
    @api.depends("state", "ev_phase_courante_id", "ev_can_agir",
                 "ev_etape_ids.state", "ev_etape_ids.validator_id",
                 "employee_feedback_published", "manager_feedback_published")
    def _compute_ev_notation_modifiable(self):
        for appraisal in self:
            appraisal.ev_notation_modifiable = not \
                appraisal._ev_motif_notation_fermee(colonne="manager")
            appraisal.ev_auto_modifiable = not \
                appraisal._ev_motif_notation_fermee(colonne="agent")

    @api.depends("ev_etape_ids.state", "ev_etape_ids.saisie_notation",
                 "ev_etape_ids.acteur")
    def _compute_ev_auto_active(self):
        """L'auto-évaluation est-elle prévue sur CETTE évaluation ?

        On lit la photo du circuit, pas le paramètre : le réglage a été
        lu au lancement, et une campagne déjà ouverte ne doit pas changer
        de règle en cours de route.
        """
        for appraisal in self:
            etapes = appraisal.sudo().ev_etape_ids.filtered(
                lambda e: e.saisie_notation and e.acteur == "agent")
            appraisal.ev_auto_evaluation_active = bool(
                etapes and any(e.state != "skipped" for e in etapes))

    @api.depends_context("uid")
    @api.depends("employee_feedback_published", "manager_feedback_published",
                 "employee_id", "ev_auto_evaluation_active")
    def _compute_ev_visibilite(self):
        """Qui voit quoi : chacun voit toujours SA colonne ; celle de
        l'autre n'apparaît qu'une fois publiée. Les RH voient tout — ils
        instruisent le dossier."""
        est_rh = self.env.user.has_group(
            "hr_appraisal.group_hr_appraisal_user")
        for appraisal in self:
            est_agent = appraisal._ev_est_agent()
            appraisal.ev_voir_notes_agent = bool(
                appraisal.ev_auto_evaluation_active
                and (est_rh or est_agent
                     or appraisal.employee_feedback_published))
            appraisal.ev_voir_notes_manager = bool(
                est_rh or not est_agent
                or appraisal.manager_feedback_published)

    # La note dépend AUSSI de la structure de la grille : un critère
    # déplacé d'un thème à l'autre change les moyennes. Sans ces
    # dépendances, la note stockée resterait figée pendant que la fiche
    # imprimée, elle, recalculerait — deux vérités pour une évaluation.
    @api.depends("ev_note_ids.valeur_manager",
                 "ev_note_ids.niveau_manager_id",
                 "ev_note_ids.valeur_agent", "ev_note_ids.niveau_agent_id",
                 "ev_grille_id",
                 "ev_grille_id.critere_ids.theme_id",
                 "ev_grille_id.theme_ids.bloc_id",
                 "ev_grille_id.mode_notation",
                 "ev_note_ids.valeur_manager", "ev_note_ids.valeur_agent")
    def _compute_ev_notation(self):
        """Deux notes, même calcul : celle du manager fait foi, celle de
        l'agent sert de comparaison."""
        for appraisal in self:
            lignes = appraisal.sudo().ev_note_ids
            grille = appraisal.sudo().ev_grille_id
            # En mode Points, la ligne n'a pas de niveau : elle porte
            # directement une valeur. Sans ce second cas, la notation
            # comptait zéro ligne notée et la note restait à 0.
            en_points = grille.mode_notation == "points"
            notees = lignes.filtered(
                lambda l: l.valeur_manager if en_points else l.niveau_manager_id)
            auto = lignes.filtered(
                lambda l: l.valeur_agent if en_points else l.niveau_agent_id)
            appraisal.ev_nb_criteres = len(lignes)
            appraisal.ev_nb_notes = len(notees)
            appraisal.ev_nb_notes_agent = len(auto)
            appraisal.ev_notation_complete = bool(
                lignes and len(notees) == len(lignes))
            appraisal.ev_agent_complete = bool(
                lignes and len(auto) == len(lignes))
            # Évaluation clôturée : on restitue la note ARRÊTÉE ce jour-là.
            # Les compteurs, eux, se recalculent sans risque : ils portent
            # sur les lignes de notation, qui sont la photo de la grille et
            # ne bougent pas.
            if appraisal.ev_note_figee:
                appraisal.ev_note_globale = appraisal.ev_note_globale_figee
                appraisal.ev_note_agent = appraisal.ev_note_agent_figee
                appraisal.ev_ecart_note = appraisal.ev_ecart_note_figee
                continue
            note_manager = grille._score(
                {l.critere_id.id: l.valeur_manager for l in notees}
            ) if grille else None
            note_agent = grille._score(
                {l.critere_id.id: l.valeur_agent for l in auto}
            ) if grille else None
            appraisal.ev_note_globale = note_manager or 0.0
            appraisal.ev_note_agent = note_agent or 0.0
            appraisal.ev_ecart_note = (
                (note_manager - note_agent)
                if note_manager is not None and note_agent is not None
                else 0.0)

    @api.depends("ev_note_ids.valeur_manager",
                 "ev_note_ids.niveau_manager_id",
                 "ev_note_ids.valeur_agent", "ev_note_ids.niveau_agent_id",
                 "ev_grille_id")
    def _compute_ev_detail(self):
        """Restitution à l'image de la fiche papier, en DEUX colonnes :
        l'auto-évaluation de l'agent en regard de la note du manager —
        c'est là que l'entretien se prépare. Une colonne non publiée
        reste masquée à l'autre partie."""
        for appraisal in self:
            grille = appraisal.sudo().ev_grille_id
            if not grille:
                appraisal.ev_notation_detail = False
                continue
            voir_agent = appraisal.ev_voir_notes_agent
            voir_manager = appraisal.ev_voir_notes_manager
            lignes = appraisal.sudo().ev_note_ids
            notes_agent = {l.critere_id.id: l.valeur_agent
                           for l in lignes if l.niveau_agent_id}
            notes_manager = {l.critere_id.id: l.valeur_manager
                             for l in lignes if l.niveau_manager_id}

            def afficher(score, visible):
                if not visible:
                    return "<span class='text-muted'>non publié</span>"
                return ("%.2f" % score) if score is not None else "—"

            def ligne(libelle, retrait, sa, sm, gras=False, muet=False):
                ouvre, ferme = ("<b>", "</b>") if gras else ("", "")
                return (
                    "<tr%s><td style='padding-left:%dpx'>%s%s%s</td>"
                    "<td class='text-end'>%s%s%s</td>"
                    "<td class='text-end'>%s%s%s</td></tr>" % (
                        " class='text-muted'" if muet else "",
                        retrait, ouvre, libelle or "", ferme,
                        ouvre, afficher(sa, voir_agent), ferme,
                        ouvre, afficher(sm, voir_manager), ferme))

            lignes = ["<table class='table table-sm o_main_table'>",
                      "<thead><tr><th>Élément</th>"
                      "<th class='text-end' style='width:9em'>Auto-évaluation</th>"
                      "<th class='text-end' style='width:9em'>Manager</th>"
                      "</tr></thead><tbody>"]
            for bloc in grille.bloc_ids:
                lignes.append(ligne(bloc.name, 8, bloc._score(notes_agent),
                                    bloc._score(notes_manager), gras=True))
                for theme in bloc.theme_ids:
                    lignes.append(ligne(
                        "<i>%s</i>" % (theme.name or ""), 30,
                        theme._score(notes_agent),
                        theme._score(notes_manager)))
                    for critere in theme.critere_ids:
                        lignes.append(ligne(
                            critere.name, 52,
                            notes_agent.get(critere.id),
                            notes_manager.get(critere.id), muet=True))
            lignes.append(ligne("NOTE GLOBALE", 8, grille._score(notes_agent),
                                grille._score(notes_manager), gras=True))
            lignes.append("</tbody></table>")
            appraisal.ev_notation_detail = "".join(lignes)

    def _ev_creer_notation(self, grille):
        """Pose la grille sur l'évaluation et crée une ligne par critère."""
        # Création SYSTÈME : les lignes naissent vides, aucun contrôle de
        # saisie ne s'applique (personne n'a encore rien noté).
        Ligne = self.env["ev.notation.ligne"].sudo().with_context(
            ev_notation_systeme=True)
        for appraisal in self:
            if appraisal.ev_note_ids:
                continue
            appraisal.ev_grille_id = grille
            vals = []
            seq = 0
            for critere in grille.critere_ids:
                seq += 10
                vals.append({
                    "appraisal_id": appraisal.id,
                    "critere_id": critere.id,
                    "sequence": seq,
                })
            if vals:
                Ligne.create(vals)

    # --- Objectifs de CETTE campagne (jamais ceux des exercices passés) ---
    ev_objectif_ids = fields.Many2many(
        "hr.appraisal.goal", string="Objectifs de la campagne",
        compute="_compute_ev_objectifs")
    ev_objectif_count = fields.Integer(
        string="Objectifs fixés", compute="_compute_ev_objectifs")
    ev_objectifs_modifiable = fields.Boolean(
        string="Objectifs modifiables", compute="_compute_ev_objectifs_droit",
        help="Vrai si l'utilisateur courant peut fixer les objectifs de "
             "l'agent à ce moment du circuit.")
    ev_avancement_modifiable = fields.Boolean(
        string="Avancement déclarable", compute="_compute_ev_objectifs_droit",
        help="Vrai si l'utilisateur courant peut déclarer où en sont les "
             "objectifs. C'est l'affaire de l'agent, tout au long de "
             "l'exercice, jusqu'à ce qu'il publie son auto-évaluation.")
    ev_entretien_modifiable = fields.Boolean(
        string="Entretien à fixer", compute="_compute_ev_objectifs_droit",
        help="Vrai si l'utilisateur courant peut fixer la date de "
             "l'entretien annuel à ce moment du circuit.")

    @api.depends("employee_id", "ev_campagne_id")
    def _compute_ev_objectifs(self):
        # sudo() : un utilisateur portail n'a aucun droit sur les objectifs
        # (le standard ne les ouvre qu'aux internes). C'est le contrôleur et
        # `_ev_motif_objectifs_fermes` qui décident de ce qu'il voit.
        Goal = self.env["hr.appraisal.goal"].sudo()
        for appraisal in self:
            if appraisal.ev_campagne_id and appraisal.employee_id:
                # Par l'EXERCICE : l'objectif a été fixé en janvier au
                # titre d'une période, la campagne n'existait pas encore.
                objectifs = Goal.search([
                    ("employee_id", "=", appraisal.employee_id.id),
                    ("ev_exercice", "=", appraisal.ev_campagne_id.exercice),
                ])
            else:
                objectifs = Goal
            appraisal.ev_objectif_ids = objectifs
            appraisal.ev_objectif_count = len(objectifs)

    # ------------------------------------------------------------------
    # La mesure des activités — le coeur de la fiche
    # ------------------------------------------------------------------
    # La mesure appartient à l'ÉVALUATION, pas à l'activité : l'activité
    # est la commande de janvier, la mesure le constat de décembre. Sans
    # cette séparation, relancer une campagne sur le même exercice
    # retrouvait les mesures de la précédente.
    ev_mesure_ids = fields.One2many(
        "ev.activite.mesure", "appraisal_id", string="Mesure des activités")
    ev_activite_ids = fields.Many2many(
        "ev.objectif.activite", string="Activités de l'exercice",
        compute="_compute_ev_activites")
    ev_activites_total = fields.Integer(
        string="Activités", compute="_compute_ev_activites")
    ev_activites_mesurees = fields.Integer(
        string="Activités mesurées", compute="_compute_ev_activites")
    ev_note_objectifs = fields.Float(
        string="Note des objectifs", digits=(5, 2),
        compute="_compute_ev_activites",
        help="Moyenne des notes des activités mesurées. Toutes les "
             "activités pèsent pareil.")
    ev_note_objectifs_max = fields.Float(
        string="Note maximale des objectifs", digits=(5, 2),
        compute="_compute_ev_activites",
        help="La note la plus haute de la grille de concordance : c'est le "
             "« sur combien » du bloc objectifs.")

    @api.depends("ev_objectif_ids", "ev_objectif_ids.ev_activite_ids",
                 "ev_mesure_ids.note", "ev_mesure_ids.mesuree")
    def _compute_ev_activites(self):
        Table = self.env["ev.taux.note"].sudo()
        for appraisal in self:
            activites = appraisal.ev_objectif_ids.ev_activite_ids
            mesurees = appraisal.ev_mesure_ids.filtered("mesuree")
            appraisal.ev_activite_ids = activites
            appraisal.ev_activites_total = len(activites)
            appraisal.ev_activites_mesurees = len(mesurees)
            # Moyenne des NOTES, toutes activités confondues : c'est la
            # règle arrêtée avec la banque, et elle ne repasse pas par
            # l'objectif — un objectif découpé en quatre activités pèse
            # quatre fois plus, c'est assumé.
            appraisal.ev_note_objectifs = (
                sum(mesurees.mapped("note")) / len(mesurees)
                if mesurees else 0.0)
            appraisal.ev_note_objectifs_max = Table.note_maximale(
                appraisal.company_id or self.env.company)

    def _ev_sync_mesures(self):
        """Une ligne de mesure par activité de l'exercice.

        Appelée à l'ouverture de l'écran et avant toute saisie : la
        période peut être rouverte après le lancement de la campagne, et
        de nouvelles activités apparaître. On ne supprime jamais une
        ligne déjà renseignée — seulement on complète ce qui manque.
        """
        Mesure = self.env["ev.activite.mesure"].sudo()
        a_creer = []
        for appraisal in self:
            existantes = appraisal.ev_mesure_ids.activite_id
            for activite in appraisal.ev_objectif_ids.ev_activite_ids:
                if activite not in existantes:
                    a_creer.append({"appraisal_id": appraisal.id,
                                    "activite_id": activite.id})
        if a_creer:
            Mesure.create(a_creer)
        return self.ev_mesure_ids

    def _ev_check_mesure(self):
        """Qui peut mesurer, et quand : exactement les mêmes conditions que
        la notation du responsable. Mesurer, c'est noter."""
        self.ensure_one()
        motif = self._ev_motif_notation_fermee(colonne="manager")
        if motif:
            raise UserError(motif)

    def _ev_mesurer(self, valeurs):
        """Reporte la saisie du formulaire sur les mesures.

        `valeurs` porte, par mesure : `atteint_<id>` et `taux_<id>`.
        On ne touche QU'AUX mesures de cette évaluation — un identifiant
        venu d'ailleurs n'atteint rien.
        """
        self.ensure_one()
        self._ev_check_mesure()
        self._ev_sync_mesures()
        for mesure in self.ev_mesure_ids:
            ecriture = {}
            atteint = valeurs.get("atteint_%s" % mesure.id)
            if atteint is not None:
                ecriture["resultat_atteint"] = atteint.strip() or False
            brut = (valeurs.get("taux_%s" % mesure.id) or "").strip()
            if brut:
                brut = brut.replace(",", ".").replace("%", "").strip()
                try:
                    taux = float(brut)
                except ValueError:
                    raise UserError(_(
                        "Taux de réalisation invalide pour « %(act)s » : "
                        "« %(val)s ». Attendu un nombre entre 0 et 100.",
                        act=mesure.name or "", val=brut))
                ecriture["taux_realisation"] = taux
            if ecriture:
                mesure.sudo().write(ecriture)

    def _ev_mesures_par_objectif(self):
        """Les mesures regroupées par objectif : [(objectif, mesures)]."""
        self.ensure_one()
        self._ev_sync_mesures()
        groupes = []
        for objectif in self.ev_objectif_ids:
            groupes.append((objectif, self.ev_mesure_ids.filtered(
                lambda m: m.goal_id == objectif)))
        return groupes

    ev_note_finale = fields.Float(
        string="Note globale", digits=(5, 2),
        compute="_compute_ev_note_finale",
        help="Somme pondérée des sections, ramenée sur 20.")
    ev_note_finale_max = fields.Float(
        string="Note globale maximale", digits=(5, 2),
        compute="_compute_ev_note_finale")
    ev_note_finale_pct = fields.Float(
        string="Note globale (%)", digits=(5, 2),
        compute="_compute_ev_note_finale")
    ev_note_finale_sur10 = fields.Float(
        string="Note ramenée sur 10", digits=(5, 2),
        compute="_compute_ev_note_finale")
    ev_notation_en_points = fields.Boolean(
        string="Notation en points", compute="_compute_ev_note_finale",
        help="La grille de cette évaluation se note-t-elle en points ?")

    # La note finale est arrêtée sur 20 : c'est le format de la fiche de
    # la banque. Le passage par les pourcentages permet à la RH d'ajouter
    # une section sans que le barème se déforme.
    EV_NOTE_SUR = 20.0

    def _ev_sections(self):
        """Le détail de la fiche, section par section.

        Renvoie une liste de dictionnaires : le bloc, ce qui a été obtenu,
        le maximum de la section, le score ramené sur 100, le poids, et
        les points que la section rapporte à la note finale.

        Deux natures de section :
        * OBJECTIFS — pas de critère ; le score vient des taux de
          réalisation, convertis par la grille de concordance ;
        * QUESTIONS — les critères rédigés par la RH, notés en points.
        """
        self.ensure_one()
        notes = {l.critere_id.id: l.valeur_manager for l in self.ev_note_ids}
        sections = []
        for bloc in self.ev_grille_id.bloc_ids:
            if bloc.type_section == "objectifs":
                obtenu = self.ev_note_objectifs
                maximum = self.ev_note_objectifs_max
            else:
                obtenu = sum(notes.get(c.id) or 0.0
                             for c in bloc.theme_ids.critere_ids)
                maximum = bloc.points_total
            pct = (obtenu * 100.0 / maximum) if maximum else 0.0
            sections.append({
                "bloc": bloc,
                "obtenu": obtenu,
                "maximum": maximum,
                "pourcentage": pct,
                "poids": bloc.poids,
                "apport": pct * bloc.poids / 100.0,
            })
        return sections

    @api.depends("ev_note_globale", "ev_note_objectifs",
                 "ev_note_objectifs_max", "ev_grille_id.mode_notation",
                 "ev_grille_id.bloc_ids.poids",
                 "ev_note_ids.valeur_manager")
    def _compute_ev_note_finale(self):
        for appraisal in self:
            en_points = appraisal.ev_grille_id.mode_notation == "points"
            appraisal.ev_notation_en_points = en_points
            if not en_points:
                appraisal.ev_note_finale = 0.0
                appraisal.ev_note_finale_max = 0.0
                appraisal.ev_note_finale_pct = 0.0
                appraisal.ev_note_finale_sur10 = 0.0
                continue
            pct = sum(s["apport"] for s in appraisal._ev_sections())
            appraisal.ev_note_finale_pct = pct
            appraisal.ev_note_finale_max = self.EV_NOTE_SUR
            appraisal.ev_note_finale = pct * self.EV_NOTE_SUR / 100.0
            appraisal.ev_note_finale_sur10 = pct / 10.0

    def _ev_motif_objectifs_fermes(self):
        """None si l'utilisateur peut fixer les objectifs de cet agent,
        sinon le motif du refus.

        Les objectifs se fixent en DÉBUT D'EXERCICE, pendant une période
        que le service RH ouvre pour toute la campagne — pas au moment
        d'évaluer. La fenêtre est donc portée par la campagne, et non par
        l'avancement de tel ou tel dossier.

        Reste la question du QUI : chaque responsable ne fixe que les
        objectifs de ses propres collaborateurs.
        """
        self.ensure_one()
        if self.state == "done":
            return _(
                "L'évaluation de %s est clôturée : ses objectifs sont ceux "
                "de l'exercice écoulé, ils ne se réécrivent plus.",
                self.sudo().employee_id.name or "")
        if self.state == "cancel":
            return _(
                "L'évaluation de %s est annulée : ses objectifs ne se "
                "modifient plus.", self.sudo().employee_id.name or "")
        if self.env.user.has_group("hr_appraisal.group_hr_appraisal_user"):
            return None
        campagne = self.sudo().ev_campagne_id
        if not campagne:
            return _(
                "Cette évaluation n'est rattachée à aucune campagne : seul "
                "le service RH peut lui fixer des objectifs.")
        motif = campagne._ev_motif_objectifs_fermes()
        if motif:
            return motif
        if not self._ev_est_evaluateur():
            return _(
                "Vous n'êtes pas le responsable de %s : ses objectifs sont "
                "fixés par son supérieur hiérarchique.",
                self.sudo().employee_id.name or "")
        return None

    def _ev_est_evaluateur(self):
        """L'utilisateur courant est-il le responsable de cet agent ?"""
        self.ensure_one()
        fiche = self.sudo()
        mes_employes = self._ev_employes_utilisateur()
        if not mes_employes:
            return False
        if fiche.manager_ids & mes_employes:
            return True
        etape = fiche.ev_etape_ids.filtered("saisie_objectifs")[:1]
        return bool(etape and etape.validator_id in mes_employes)

    def _ev_demarrer_evaluation(self):
        """Ferme le temps des objectifs et met le circuit en marche.

        Appelé par le service RH sur toute la campagne, en fin
        d'exercice. La phase des objectifs encore en cours est acquise
        telle quelle — le retard d'un responsable ne doit pas bloquer
        l'agent (décision de la banque : on laisse passer, on signale).
        """
        self.ensure_one()
        if self.state in ("done", "cancel"):
            return
        fiche = self.sudo()
        en_cours = fiche.ev_etape_ids.filtered(
            lambda e: e.saisie_objectifs and e.state == "pending")
        if en_cours:
            en_cours.write({
                "state": "done",
                "acted_by_id": self.env.uid,
                "date_action": fields.Datetime.now(),
            })
        if fiche.ev_etape_ids.filtered(lambda e: e.state == "pending"):
            return
        suivante = fiche.ev_etape_ids.filtered(
            lambda e: e.state == "waiting")[:1]
        if suivante:
            suivante.state = "pending"

    def _ev_motif_avancement_ferme(self):
        """None si l'utilisateur courant peut declarer l'avancement des
        objectifs, sinon le motif du refus.

        L'avancement se declare tout au long de l'exercice, et il se
        declare par l'AGENT : c'est lui qui fait le travail, lui qui sait
        ou il en est. Ce n'est donc pas une saisie de phase.

        Une seule borne : la publication de l'auto-evaluation. A ce
        moment, l'agent a arrete son bilan de l'annee ; laisser bouger
        l'avancement ensuite reviendrait a modifier, sous les yeux du
        responsable, la piece meme qu'il est en train de juger.
        """
        self.ensure_one()
        if self.state == "done":
            return _(
                "L'évaluation est clôturée : l'avancement des objectifs "
                "est celui de l'exercice écoulé.")
        if self.state == "cancel":
            return _("L'évaluation est annulée.")
        if self.env.user.has_group("hr_appraisal.group_hr_appraisal_user"):
            return None
        if not self._ev_est_agent():
            return _(
                "L'avancement des objectifs se déclare par %s : c'est lui "
                "qui sait où il en est.", self.sudo().employee_id.name or "")
        if self.employee_feedback_published:
            return _(
                "Votre auto-évaluation est publiée : votre bilan de "
                "l'année est arrêté, l'avancement ne se modifie plus.")
        return None

    def _ev_objectif_avancement(self, avancements):
        """Enregistre l'avancement declare par l'agent.

        ``avancements`` : {id d'objectif: valeur de progression}. On ne
        retient QUE les objectifs de cette evaluation - c'est ce filtre
        qui empeche de faire avancer, par un identifiant devine, celui
        d'un collegue.
        """
        self.ensure_one()
        motif = self._ev_motif_avancement_ferme()
        if motif:
            raise UserError(motif)
        Goal = self.env["hr.appraisal.goal"]
        valides = dict(Goal._fields["progression"].selection)
        objectifs = {g.id: g for g in self.ev_objectif_ids}
        for brut_id, valeur in (avancements or {}).items():
            try:
                objectif = objectifs.get(int(brut_id))
            except (ValueError, TypeError):
                continue
            if not objectif or valeur not in valides:
                continue
            if objectif.progression != valeur:
                objectif.sudo().write({"progression": valeur})

    # ------------------------------------------------------------------
    # L'entretien : dernier temps du circuit
    # ------------------------------------------------------------------
    def _ev_motif_entretien_ferme(self):
        """None si l'utilisateur courant peut fixer la date de l'entretien,
        sinon le motif du refus.

        L'entretien revient au superieur direct : la note est arretee, il
        reste a la restituer de vive voix. Il fixe la date, puis declare
        l'entretien realise en validant sa phase - ce qui clot
        l'evaluation.
        """
        self.ensure_one()
        if self.state == "done":
            return _("L'évaluation est clôturée : l'entretien a eu lieu.")
        if self.state == "cancel":
            return _("L'évaluation est annulée.")
        if self.env.user.has_group("hr_appraisal.group_hr_appraisal_user"):
            return None
        phase = self.sudo().ev_phase_courante_id
        if not phase:
            return _(
                "Aucune phase du circuit n'est en cours : seul le service "
                "RH peut intervenir.")
        if not self.ev_can_agir:
            attendu = (phase.sudo().validator_id.name if phase.validator_id
                       else _("le service RH"))
            return _(
                "La phase « %(phase)s » attend l'action de %(qui)s.",
                phase=phase.name, qui=attendu)
        if not phase.saisie_entretien:
            return _(
                "La phase « %(phase)s » ne porte pas l'entretien : celui-ci "
                "se fixe en fin de circuit, une fois la notation arrêtée.",
                phase=phase.name)
        return None

    def _ev_fixer_entretien(self, date_entretien, heure_entretien=None):
        """Planifie l'entretien annuel.

        ATTENTION : ``date_final_interview`` n'est PAS un champ stocke.
        C'est un calcul d'Odoo a partir des rendez-vous rattaches a
        l'evaluation (``meeting_ids``). Y ecrire directement ne persiste
        rien - l'ecriture est silencieusement perdue au recalcul suivant.

        L'entretien se pose donc comme un vrai **rendez-vous**, ce qu'il
        est : le collaborateur et son responsable y sont convies, il
        apparait dans leurs agendas, et le back-office le retrouve la ou
        il l'attend. Reprogrammer deplace le rendez-vous existant plutot
        que d'en empiler un second.
        """
        self.ensure_one()
        motif = self._ev_motif_entretien_ferme()
        if motif:
            raise UserError(motif)
        if not date_entretien:
            raise UserError(_("Indiquez la date de l'entretien."))
        try:
            jour = fields.Date.to_date(date_entretien)
        except (ValueError, TypeError):
            raise UserError(_(
                "La date « %s » n'est pas une date valide.", date_entretien))
        debut_heure = time(9, 0)
        if heure_entretien:
            try:
                heures, minutes = str(heure_entretien).split(":")[:2]
                debut_heure = time(int(heures), int(minutes))
            except (ValueError, TypeError):
                raise UserError(_(
                    "L'heure « %s » n'est pas une heure valide.",
                    heure_entretien))
        # Un entretien annuel se tient : on ne le programme pas dans le
        # passe, et il appartient a l'exercice de la campagne.
        if jour < fields.Date.context_today(self):
            raise UserError(_(
                "Le %s est déjà passé : on ne programme pas un entretien "
                "dans le passé. Indiquez la date à laquelle il se tiendra.",
                fields.Date.to_string(jour)))
        campagne = self.sudo().ev_campagne_id
        if campagne and campagne.date_fin and jour > campagne.date_fin:
            raise UserError(_(
                "L'entretien serait fixé au %(jour)s, après la fin de la "
                "campagne « %(campagne)s » (%(fin)s). Corrigez la date, ou "
                "demandez au service RH de prolonger la campagne.",
                jour=fields.Date.to_string(jour), campagne=campagne.name,
                fin=fields.Date.to_string(campagne.date_fin)))
        debut = datetime.combine(jour, debut_heure)
        fin = debut + timedelta(hours=1)

        fiche = self.sudo()
        # Les deux interesses : l'agent et celui qui mene l'entretien. On
        # accepte les deux conventions de rattachement, comme partout.
        employe = fiche.employee_id
        partenaires = employe.work_contact_id | employe.user_id.partner_id
        if self.env.user.partner_id:
            partenaires |= self.env.user.partner_id
        valeurs = {
            "name": _("Entretien annuel — %s", employe.name or ""),
            "start": debut,
            "stop": fin,
            "duration": 1.0,
            "partner_ids": [(6, 0, partenaires.ids)],
        }
        rdv = fiche.meeting_ids[:1]
        if rdv:
            rdv.sudo().write(valeurs)
        else:
            rdv = self.env["calendar.event"].sudo().create(valeurs)
            fiche.write({"meeting_ids": [(4, rdv.id)]})
        self.message_post(body=_(
            "Entretien fixé au %(date)s à %(heure)s par %(user)s.",
            date=fields.Date.to_string(jour),
            heure=debut_heure.strftime("%H:%M"),
            user=self.env.user.name))

    def _ev_deposer_compte_rendu(self, contenu, nom_fichier):
        """Enregistre la pièce de l'entretien.

        Mêmes droits que la fixation de la date : c'est l'affaire de
        celui qui mène l'entretien, pendant la phase qui la porte.
        """
        self.ensure_one()
        motif = self._ev_motif_entretien_ferme()
        if motif:
            raise UserError(motif)
        if not contenu:
            raise UserError(_("Choisissez un fichier à déposer."))
        self.sudo().write({
            "ev_compte_rendu": contenu,
            "ev_compte_rendu_nom": nom_fichier or _("compte-rendu"),
        })
        self.message_post(body=_(
            "Compte-rendu d'entretien déposé par %(user)s : %(fichier)s.",
            user=self.env.user.name,
            fichier=nom_fichier or _("document")))

    @api.depends_context("uid")
    @api.depends("state", "ev_phase_courante_id", "ev_can_agir",
                 "employee_feedback_published")
    def _compute_ev_objectifs_droit(self):
        for appraisal in self:
            appraisal.ev_objectifs_modifiable = not \
                appraisal._ev_motif_objectifs_fermes()
            appraisal.ev_avancement_modifiable = not \
                appraisal._ev_motif_avancement_ferme()
            appraisal.ev_entretien_modifiable = not \
                appraisal._ev_motif_entretien_ferme()

    # ------------------------------------------------------------------
    # Écriture des objectifs depuis le portail
    # ------------------------------------------------------------------
    # Le portail n'a aucun droit sur ``hr.appraisal.goal`` — le standard ne
    # l'ouvre qu'aux utilisateurs internes. Il passe donc par ces méthodes,
    # qui vérifient d'abord, écrivent en sudo ensuite. Toute la règle est
    # ici, dans le module métier : le connecteur ne fait que relayer.
    def _ev_check_objectifs(self):
        motif = self._ev_motif_objectifs_fermes()
        if motif:
            raise UserError(motif)

    def _ev_objectif_creer(self, libelle, echeance=None, description=None):
        """Ajoute un objectif à l'agent, au titre de CETTE campagne."""
        self.ensure_one()
        self._ev_check_objectifs()
        libelle = (libelle or "").strip()
        if not libelle:
            raise UserError(_("Un objectif doit avoir un intitulé."))
        # Un objectif s'énonce en une phrase. Sans borne, un copier-coller
        # malheureux déforme durablement le tableau de l'agent.
        if len(libelle) > 200:
            raise UserError(_(
                "L'intitulé de l'objectif est trop long (%(n)s caractères "
                "pour %(max)s au maximum). Résumez-le en une phrase et "
                "mettez le détail dans les précisions.",
                n=len(libelle), max=200))
        # Deux objectifs identiques n'ont pas de sens, et un double clic
        # sur « Ajouter » suffisait à en créer trois.
        if any(g.name.strip().lower() == libelle.lower()
               for g in self.ev_objectif_ids):
            raise UserError(_(
                "« %s » figure déjà parmi les objectifs de cet exercice.",
                libelle))
        # La saisie vient d'un formulaire web : on ne présume rien de sa
        # forme. Une date illisible doit produire un message clair, pas une
        # page d'erreur.
        if echeance:
            try:
                echeance = fields.Date.to_date(echeance)
            except (ValueError, TypeError):
                raise UserError(_(
                    "L'échéance « %s » n'est pas une date valide.", echeance))
        fiche = self.sudo()
        # ``manager_id`` est obligatoire sur le standard, et son calcul par
        # défaut s'appuie sur ``env.user.employee_id`` — vide pour un
        # utilisateur portail. On le renseigne donc explicitement : le
        # responsable hiérarchique de l'agent, ou à défaut l'acteur de la
        # phase en cours, qui est bien celui qui passe la commande.
        phase = fiche.ev_phase_courante_id
        manager = fiche.employee_id.parent_id or phase.validator_id
        if not manager:
            manager = fiche.manager_ids[:1]
        if not manager:
            raise UserError(_(
                "Aucun responsable n'est identifié pour %s : impossible de "
                "lui fixer un objectif. Le service RH doit d'abord "
                "renseigner son supérieur hiérarchique.",
                fiche.employee_id.name or ""))
        return self.env["hr.appraisal.goal"].sudo().create({
            "name": libelle,
            "employee_id": fiche.employee_id.id,
            "manager_id": manager.id,
            "ev_campagne_id": fiche.ev_campagne_id.id,
            "deadline": echeance or False,
            "description": description or False,
        })

    def _ev_objectif_supprimer(self, objectif_id):
        """Retire un objectif — uniquement parmi ceux de cette évaluation."""
        self.ensure_one()
        self._ev_check_objectifs()
        try:
            objectif_id = int(objectif_id)
        except (ValueError, TypeError):
            raise UserError(_("Objectif introuvable."))
        # On ne cherche QUE parmi les objectifs de cette évaluation : c'est
        # ce filtre qui empêche de supprimer, par un identifiant deviné,
        # l'objectif de quelqu'un d'autre.
        objectif = self.ev_objectif_ids.filtered(
            lambda g: g.id == objectif_id)
        if not objectif:
            raise UserError(_(
                "Cet objectif n'appartient pas à l'évaluation en cours."))
        objectif.sudo().unlink()

    def action_ev_voir_objectifs(self):
        """Les objectifs de l'agent POUR CETTE CAMPAGNE, avec création
        pré-remplie : on ne mélange jamais deux exercices."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Objectifs — %s", self.employee_id.name),
            "res_model": "hr.appraisal.goal",
            "view_mode": "tree,form",
            "domain": [("employee_id", "=", self.employee_id.id),
                       ("ev_campagne_id", "=", self.ev_campagne_id.id)],
            "context": {
                "default_employee_id": self.employee_id.id,
                "default_manager_id": self.manager_ids[:1].id,
                "default_ev_campagne_id": self.ev_campagne_id.id,
                "default_deadline": self.ev_campagne_id.date_fin,
            },
        }

    def action_ev_export_fiche(self):
        """Télécharge la fiche d'évaluation remplie, au format Excel."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "target": "self",
            "url": "/gestion_evaluation/fiche/%s.xlsx" % self.id,
        }

    @api.depends("ev_etape_ids.state")
    def _compute_ev_circuit_en_cours(self):
        for appraisal in self:
            appraisal.ev_circuit_en_cours = bool(
                appraisal.ev_etape_ids.filtered(
                    lambda e: e.state in ("waiting", "pending")))

    @api.depends("ev_etape_ids.state", "ev_etape_ids.validator_id")
    def _compute_ev_phase_courante(self):
        for appraisal in self:
            phase = appraisal.ev_etape_ids.filtered(
                lambda e: e.state == "pending")[:1]
            appraisal.ev_phase_courante_id = phase
            appraisal.ev_acteur_courant_id = phase.validator_id

    # --- L'entretien tel qu'il a été programmé ---------------------------
    # Odoo n'expose qu'une DATE (`date_final_interview`, calculée depuis
    # les rendez-vous). L'agent convoqué a besoin de l'heure : on lit
    # directement le rendez-vous.
    ev_entretien_debut = fields.Datetime(
        string="Entretien programmé", compute="_compute_ev_entretien",
        help="Date et heure du rendez-vous d'entretien annuel.")
    ev_entretien_avec = fields.Char(
        string="Entretien avec", compute="_compute_ev_entretien")

    # L'entretien est le seul moment du circuit qui se passe hors du
    # logiciel : deux personnes dans un bureau. Il n'en reste rien, sauf
    # ce que le responsable y dépose. La banque exige cette pièce avant
    # la clôture — sans elle, rien ne prouve que l'entretien s'est tenu,
    # ni ce qui s'y est dit. Le service RH la voit sur la fiche.
    ev_compte_rendu = fields.Binary(
        string="Compte-rendu d'entretien", attachment=True, copy=False,
        help="Document déposé par le responsable à l'issue de l'entretien "
             "(compte-rendu, fiche signée...). Obligatoire avant la "
             "clôture de l'évaluation.")
    ev_compte_rendu_nom = fields.Char(
        string="Nom du fichier", copy=False)

    @api.depends("meeting_ids.start", "ev_etape_ids.validator_id",
                 "ev_etape_ids.saisie_entretien")
    def _compute_ev_entretien(self):
        for appraisal in self:
            # sudo() : ni le rendez-vous ni les fiches employé ne sont
            # lisibles par un utilisateur portail.
            fiche = appraisal.sudo()
            rdv = fiche.meeting_ids[:1]
            appraisal.ev_entretien_debut = rdv.start if rdv else False
            etape = fiche.ev_etape_ids.filtered("saisie_entretien")[:1]
            meneur = etape.validator_id or fiche.manager_ids[:1]
            appraisal.ev_entretien_avec = meneur.name or False

    # --- L'échelle sur laquelle CETTE évaluation se note ------------------
    ev_niveau_ids = fields.Many2many(
        "ev.echelle.niveau", string="Niveaux proposés",
        compute="_compute_ev_niveaux",
        help="L'échelle figée de la campagne. Hors campagne, l'échelle "
             "de référence en vigueur.")

    @api.depends("ev_campagne_id")
    def _compute_ev_niveaux(self):
        # sudo() : modèle technique, inaccessible à un utilisateur portail.
        Niveau = self.env["ev.echelle.niveau"].sudo()
        reference = Niveau.search([("campagne_photo_id", "=", False)])
        for appraisal in self:
            photo = appraisal.sudo().ev_campagne_id.echelle_photo_ids
            appraisal.ev_niveau_ids = photo or reference

    # --- Ce qu'on demande de corriger ------------------------------------
    # Le commentaire de renvoi est OBLIGATOIRE à la saisie ; il ne servait
    # pourtant à rien, faute d'être affiché nulle part. Celui à qui le
    # dossier revient doit lire ce qu'on attend de lui.
    ev_motif_renvoi = fields.Text(
        string="Motif du renvoi", compute="_compute_ev_motif_renvoi",
        help="Ce que l'évaluateur demande de corriger. Renseigné tant que "
             "la phase renvoyée n'a pas été retraitée.")
    ev_renvoi_par = fields.Char(
        string="Renvoyé par", compute="_compute_ev_motif_renvoi")

    @api.depends("ev_phase_courante_id", "ev_etape_ids.comment",
                 "ev_etape_ids.state")
    def _compute_ev_motif_renvoi(self):
        for appraisal in self:
            # Une phase EN COURS porteuse d'un commentaire ne peut l'avoir
            # reçu que d'un renvoi : la validation, elle, commente la phase
            # qu'elle achève.
            phase = appraisal.sudo().ev_phase_courante_id
            motif = phase.comment if phase else False
            appraisal.ev_motif_renvoi = motif or False
            appraisal.ev_renvoi_par = (
                phase.acted_by_id.name if motif and phase.acted_by_id
                else False)

    @api.depends_context("uid")
    @api.depends("ev_phase_courante_id", "ev_acteur_courant_id")
    def _compute_ev_can_agir(self):
        # sudo() sur les LECTURES de fiches employé : un utilisateur
        # portail n'a pas le droit de lire hr.employee, et la moindre
        # lecture déclencherait un 403. L'identité, elle, reste celle de
        # l'utilisateur courant — c'est elle qui décide.
        mes_employes = self._ev_employes_utilisateur()
        is_rh = self.env.user.has_group("hr_appraisal.group_hr_appraisal_user")
        for appraisal in self:
            # sudo() : les étapes du circuit sont un modèle technique,
            # inaccessible à un utilisateur portail. C'est l'identité qui
            # décide, pas le droit de lecture sur la table.
            phase = appraisal.sudo().ev_phase_courante_id
            if not phase:
                appraisal.ev_can_agir = False
                continue
            # Phase confiée au service RH : tout gestionnaire peut agir.
            if phase.acteur == "rh":
                appraisal.ev_can_agir = is_rh
                continue
            appraisal.ev_can_agir = bool(
                is_rh or phase.sudo().validator_id in mes_employes)

    # ------------------------------------------------------------------
    # Verrou : le circuit prime sur la clôture directe
    # ------------------------------------------------------------------
    def _ev_message_circuit_ouvert(self):
        """Message expliquant ce qui reste à faire avant de clôturer."""
        self.ensure_one()
        restantes = self.ev_etape_ids.filtered(
            lambda e: e.state in ("waiting", "pending"))
        courante = self.ev_phase_courante_id
        attendu = (courante.sudo().validator_id.name if courante.validator_id
                   else _("le service RH")) if courante else _("personne")
        return _(
            "Cette évaluation suit un circuit : %(nb)s phase(s) restent à "
            "traiter (%(phases)s). La phase « %(courante)s » attend "
            "%(qui)s.\n\nUtilisez « Valider ma phase » pour faire avancer le "
            "circuit. L'évaluation se clôturera d'elle-même à la dernière "
            "phase.",
            nb=len(restantes),
            phases=", ".join(restantes.mapped("name")),
            courante=courante.name if courante else "-", qui=attendu)

    def action_done(self):
        """Bouton natif « Marquer comme fait ».

        Il court-circuiterait le circuit — un manager pourrait clore sans la
        validation N+2, ce que le contrôle interne bancaire interdit. On le
        bloque tant qu'il reste des phases ; le chemin légitime est de les
        valider (un gestionnaire RH peut le faire à la place de chacun).
        """
        for appraisal in self:
            if appraisal.ev_circuit_en_cours:
                raise UserError(appraisal._ev_message_circuit_ouvert())
        return super().action_done()

    def write(self, vals):
        """Même verrou côté serveur, pour toute écriture directe de l'état."""
        if vals.get("state") == "done" \
                and not self.env.context.get("ev_cloture_circuit"):
            for appraisal in self:
                if appraisal.ev_circuit_en_cours:
                    raise UserError(appraisal._ev_message_circuit_ouvert())
        # Changer la grille sous une notation déjà saisie rendrait les notes
        # incompréhensibles : elles pointeraient sur les critères d'une
        # grille qui n'est plus celle affichée.
        if "ev_grille_id" in vals \
                and not self.env.context.get("ev_notation_systeme"):
            for appraisal in self:
                if appraisal.ev_note_ids \
                        and appraisal.ev_grille_id.id != vals["ev_grille_id"]:
                    raise UserError(_(
                        "L'évaluation de %s est déjà notée avec la grille "
                        "« %s » : on ne peut plus lui en substituer une "
                        "autre. Supprimez d'abord la notation, ou repartez "
                        "d'une nouvelle évaluation.",
                        appraisal.employee_id.name or "",
                        appraisal.ev_grille_id.name or ""))
        resultat = super().write(vals)
        if "state" in vals:
            self._ev_arreter_ou_rouvrir_note(vals["state"])
        return resultat

    def _ev_arreter_ou_rouvrir_note(self, etat):
        """Arrête la note à la clôture, la libère à la réouverture.

        Passer par ``write`` plutôt que par la seule méthode de clôture :
        le service RH peut clore ou rouvrir un dossier directement depuis
        le back-office, et la note doit se figer dans tous les cas.
        """
        if etat == "done":
            for appraisal in self:
                if appraisal.ev_note_figee:
                    continue
                appraisal.sudo().write({
                    "ev_note_globale_figee": appraisal.ev_note_globale,
                    "ev_note_agent_figee": appraisal.ev_note_agent,
                    "ev_ecart_note_figee": appraisal.ev_ecart_note,
                    "ev_note_figee": True,
                })
        elif etat:
            # Rouvrir un dossier remet la note en calcul : le service RH
            # rouvre précisément pour corriger.
            figees = self.filtered("ev_note_figee")
            if figees:
                figees.sudo().write({"ev_note_figee": False})
                figees.sudo()._compute_ev_notation()

    # ------------------------------------------------------------------
    # Construction de la photo
    # ------------------------------------------------------------------
    def _ev_resoudre_acteur(self, phase):
        """Traduit un rôle de phase en une personne, pour CETTE évaluation.

        Retourne (employé, motif_de_saut). Un motif non vide signifie que la
        phase ne peut pas être jouée.
        """
        self.ensure_one()
        employee = self.employee_id
        if phase.acteur == "agent":
            return employee, False
        if phase.acteur == "rh":
            # Aucune personne précise : le service RH agit collectivement.
            return self.env["hr.employee"], False
        if phase.acteur == "fixe":
            if not phase.employee_id:
                return self.env["hr.employee"], _("aucune personne désignée")
            return phase.employee_id, False
        if phase.acteur == "n1":
            if not employee.parent_id:
                return self.env["hr.employee"], _(
                    "la fiche de %s n'a pas de supérieur hiérarchique",
                    employee.name)
            return employee.parent_id, False
        # n2
        n1 = employee.parent_id
        if not n1:
            return self.env["hr.employee"], _(
                "la fiche de %s n'a pas de supérieur hiérarchique", employee.name)
        if not n1.parent_id:
            return self.env["hr.employee"], _(
                "la fiche de %s (N+1) n'a pas de supérieur", n1.name)
        return n1.parent_id, False

    def _ev_creer_photo(self, phases=None):
        """Photographie le circuit configuré sur ces évaluations.

        Une phase dont l'acteur ne peut pas être résolu, ou qui se
        résoudrait sur l'agent évalué alors qu'elle n'est pas la sienne
        (séparation des tâches), est SAUTÉE et tracée. On ne bloque jamais :
        une campagne de 25 agents ne doit pas échouer parce que trois fiches
        sont incomplètes.
        """
        Etape = self.env["ev.evaluation.etape"].sudo()
        auto_active = self.env["ir.config_parameter"].sudo().get_param(
            "ev.auto_evaluation_active", "1") == "1"
        for appraisal in self:
            if appraisal.ev_etape_ids:
                continue
            applicables = phases if phases is not None else \
                self.env["ev.circuit.phase"].search([
                    ("company_id", "in", [False, appraisal.company_id.id])])
            if not applicables:
                continue
            lignes, sautees = [], []
            for phase in applicables:
                acteur, motif = appraisal._ev_resoudre_acteur(phase)
                if not motif and phase.acteur not in ("agent", "rh") \
                        and acteur == appraisal.employee_id:
                    motif = _("personne ne peut valider sa propre évaluation")
                # L'auto-évaluation peut être désactivée par le service RH.
                # Le réglage est lu ICI, au lancement, et photographié avec
                # le reste : le modifier ensuite ne touche pas aux campagnes
                # déjà ouvertes.
                if not motif and phase.saisie_notation \
                        and phase.acteur == "agent" \
                        and not auto_active:
                    motif = _(
                        "l'auto-évaluation est désactivée dans les "
                        "paramètres : seule la notation du responsable "
                        "compte")
                lignes.append({
                    "appraisal_id": appraisal.id,
                    "sequence": phase.sequence,
                    "name": phase.name,
                    "acteur": phase.acteur,
                    "saisie_notation": phase.saisie_notation,
                    "saisie_objectifs": phase.saisie_objectifs,
                    "saisie_entretien": phase.saisie_entretien,
                    "validator_id": acteur.id if acteur else False,
                    "state": "skipped" if motif else "waiting",
                    "skip_reason": motif or False,
                })
                if motif:
                    sautees.append("%s (%s)" % (phase.name, motif))
            etapes = Etape.create(lignes)
            premiere = etapes.filtered(lambda e: e.state == "waiting")[:1]
            if premiere:
                premiere.state = "pending"
            if sautees:
                appraisal.message_post(body=_(
                    "Circuit d'évaluation : %(nb)s phase(s) sautée(s) — "
                    "%(detail)s", nb=len(sautees), detail=" ; ".join(sautees)))
            if not premiere:
                appraisal.message_post(body=_(
                    "<b>Aucune phase du circuit n'est applicable</b> à cette "
                    "évaluation : elle devra être traitée manuellement par "
                    "le service RH."))

    # ------------------------------------------------------------------
    # Actions du circuit
    # ------------------------------------------------------------------
    def _ev_check_droits(self):
        """Qui peut traiter la phase en cours : l'acteur attendu, ou un
        gestionnaire RH. Jamais quelqu'un d'autre."""
        self.ensure_one()
        phase = self.sudo().ev_phase_courante_id
        if not phase:
            raise UserError(_(
                "Cette évaluation n'a aucune phase en attente."))
        if not self.ev_can_agir:
            attendu = phase.sudo().validator_id.name if phase.validator_id \
                else _("le service RH")
            raise UserError(_(
                "La phase « %(phase)s » attend l'action de %(qui)s.",
                phase=phase.name, qui=attendu))
        return phase

    # ------------------------------------------------------------------
    # Publication : « j'ai terminé, l'autre peut voir »
    # ------------------------------------------------------------------
    def _ev_publier(self, colonne):
        """Fige la colonne de l'utilisateur et la rend visible à l'autre.

        Publier est un acte volontaire et irréversible : on refuse tant
        que la grille n'est pas entièrement appréciée, pour éviter qu'une
        évaluation parte incomplète.
        """
        self.ensure_one()
        motif = self._ev_motif_notation_fermee(colonne=colonne)
        if motif:
            raise UserError(motif)
        # Ce qui manque est annoncé EN UNE FOIS. Refuser sur les
        # critères, puis — une fois corrigés — refuser à nouveau sur les
        # activités, ferait recommencer le responsable deux fois pour la
        # même fiche.
        manques = []
        if self.sudo().ev_grille_id:
            manquants = (self.ev_nb_criteres
                         - (self.ev_nb_notes_agent if colonne == "agent"
                            else self.ev_nb_notes))
            if manquants > 0:
                manques.append(_(
                    "%(nb)s question(s) à noter sur %(total)s",
                    nb=manquants, total=self.ev_nb_criteres))
        # Les objectifs pèsent le plus lourd de la fiche : publier en
        # ayant oublié d'en mesurer revient à noter zéro sur cette part
        # sans l'avoir voulu. L'agent, lui, ne mesure rien : ce contrôle
        # ne vise que le responsable.
        if colonne != "agent" and self.sudo().ev_activites_total:
            reste = (self.sudo().ev_activites_total
                     - self.sudo().ev_activites_mesurees)
            if reste > 0:
                manques.append(_(
                    "%(nb)s activité(s) à mesurer sur %(total)s",
                    nb=reste, total=self.sudo().ev_activites_total))
        if manques:
            raise UserError(_(
                "La fiche n'est pas complète : il reste %(manques)s. "
                "Complétez-la avant de publier.",
                manques=" et ".join(str(m) for m in manques)))
        champ = ("employee_feedback_published" if colonne == "agent"
                 else "manager_feedback_published")
        self.sudo().write({champ: True})
        self.message_post(body=(
            _("Auto-évaluation publiée par %s.", self.env.user.name)
            if colonne == "agent"
            else _("Notation publiée par %s.", self.env.user.name)))
        if colonne == "agent":
            self._ev_avancer_apres_auto()

    def _ev_avancer_apres_auto(self):
        """Publier son auto-évaluation clôt la phase qui la porte.

        L'agent n'a pas — et ne doit pas avoir — le bouton « Valider la
        phase » : celui-ci est l'acte d'un validateur, assorti d'un
        commentaire et de la possibilité de renvoyer. Or, pour l'agent,
        publier EST son acte de fin : sa colonne est figée, il n'a plus
        rien à faire. Sans cet enchaînement, le circuit restait
        indéfiniment sur « Auto-évaluation » et le manager ne pouvait
        jamais noter.

        On n'avance que si la phase en cours est bien celle de l'agent :
        si le service RH publie à sa place pour débloquer un dossier, le
        circuit ne bouge pas — c'est au RH de décider de la suite.
        """
        self.ensure_one()
        etape = self._ev_etape_de_notation("agent")
        if not etape or etape.state in ("done", "skipped"):
            return
        # La saisie est possible AVANT son tour. Si l'agent publie par
        # anticipation, sa phase est acquise mais le circuit ne bondit
        # pas : une autre phase est en cours, elle garde la main.
        etait_en_cours = etape.state == "pending"
        etape.sudo().write({
            "state": "done",
            "acted_by_id": self.env.uid,
            "date_action": fields.Datetime.now(),
            "comment": False,
        })
        self.message_post(body=_(
            "Phase « %(phase)s » achevée par la publication de "
            "l'auto-évaluation (%(user)s).",
            phase=etape.name, user=self.env.user.name))
        if not etait_en_cours:
            return
        suivante = self.ev_etape_ids.filtered(
            lambda e: e.state == "waiting")[:1]
        if suivante:
            suivante.sudo().state = "pending"
        else:
            self._ev_cloturer()

    def action_ev_publier_auto(self):
        for appraisal in self:
            appraisal._ev_publier("agent")

    def action_ev_publier_notation(self):
        for appraisal in self:
            appraisal._ev_publier("manager")

    def action_ev_valider_etape(self, comment=None):
        """Valide la phase en cours et passe à la suivante. La dernière
        phase validée marque l'évaluation comme faite."""
        for appraisal in self:
            phase = appraisal._ev_check_droits()
            appraisal._ev_check_objectifs_avant_validation(phase)
            appraisal._ev_check_publication_avant_validation(phase)
            # Déclarer qu'un entretien a eu lieu sans savoir quand n'a pas
            # de sens : c'est la trace de la restitution au collaborateur.
            # On regarde le RENDEZ-VOUS, pas `date_final_interview` : ce
            # dernier est un calcul dérivé, sensible au fuseau.
            if phase.saisie_entretien and not appraisal.sudo().ev_compte_rendu                     and not self.env.user.has_group(
                        "hr_appraisal.group_hr_appraisal_user"):
                raise UserError(_(
                    "Déposez d'abord le compte-rendu de l'entretien. "
                    "L'entretien s'est tenu hors du logiciel : cette pièce "
                    "est la seule trace de ce qui s'y est dit, et elle "
                    "restera au dossier de %s.",
                    appraisal.sudo().employee_id.name or ""))
            if phase.saisie_entretien and not appraisal.sudo().meeting_ids:
                raise UserError(_(
                    "Fixez d'abord la date de l'entretien : on ne déclare "
                    "pas un entretien réalisé sans savoir quand il a eu "
                    "lieu."))
            phase.sudo().write({
                "state": "done",
                "acted_by_id": self.env.uid,
                "date_action": fields.Datetime.now(),
                "comment": comment or False,
            })
            appraisal.message_post(body=_(
                "Phase « %(phase)s » validée par %(user)s.%(note)s",
                phase=phase.name, user=self.env.user.name,
                note=_(" Commentaire : %s", comment) if comment else ""))
            # Le responsable vient de dire « j'ai fini de fixer les
            # objectifs de cet agent ». Le circuit s'ARRÊTE là : on est en
            # début d'exercice, l'évaluation ne s'ouvrira qu'en fin
            # d'année, sur décision du service RH.
            if phase.saisie_objectifs \
                    and appraisal.sudo().ev_campagne_id.state == "objectifs":
                continue
            suivante = appraisal.ev_etape_ids.filtered(
                lambda e: e.state == "waiting")[:1]
            if suivante:
                suivante.sudo().state = "pending"
            else:
                appraisal._ev_cloturer()

    def _ev_check_objectifs_avant_validation(self, phase):
        """On ne clôt pas la phase des objectifs hors période, ni à vide.

        Deux trous constatés à l'usage :

        * la période n'était contrôlée que pour AJOUTER un objectif, pas
          pour valider la phase — un responsable pouvait donc déclarer
          « j'ai fini » avant même l'ouverture de la période ;
        * il pouvait la valider sans avoir fixé le moindre objectif, et
          l'agent partait pour l'année sans commande écrite.

        À distinguer du responsable simplement en retard : celui-là ne
        fait rien, et la banque a décidé qu'on le laisse passer avec une
        alerte au service RH (voir ``action_lancer``). Ici
        c'est un geste délibéré : on le refuse.
        """
        self.ensure_one()
        if not phase.saisie_objectifs:
            return
        est_rh = self.env.user.has_group(
            "hr_appraisal.group_hr_appraisal_user")
        motif = self._ev_motif_objectifs_fermes()
        if motif and not est_rh:
            raise UserError(motif)
        if self.sudo().ev_objectif_ids:
            return
        message = _(
            "Vous n'avez fixé aucun objectif à %s. Ajoutez-en au moins un "
            "avant de clore cette phase : sans commande écrite, il n'y "
            "aura rien à évaluer en fin d'exercice.",
            self.sudo().employee_id.name or "")
        if est_rh:
            self.message_post(body=_(
                "Phase « %(phase)s » close par le service RH SANS aucun "
                "objectif. %(motif)s", phase=phase.name, motif=message))
            return
        raise UserError(message)

    def _ev_check_publication_avant_validation(self, phase):
        """On ne valide pas une phase de notation sans avoir publié.

        Le piège était silencieux et sans retour : valider sa phase sans
        publier sa colonne faisait avancer l'évaluation avec une notation
        INVISIBLE — l'agent ne la voyait pas — et son auteur ne pouvait
        plus la publier, sa phase étant close. Le dossier partait vide
        chez le N+2, et personne ne pouvait plus rien.

        Publier et valider restent DEUX gestes distincts pour le
        responsable — publier fige sa note, valider passe la main. Mais
        l'ordre, lui, n'est pas libre.

        Le service RH n'est pas bloqué : il peut publier à la place de
        l'auteur. S'il valide malgré tout — responsable parti, dossier à
        débloquer — on le laisse faire et on en garde la trace.
        """
        self.ensure_one()
        if not phase.saisie_notation:
            return
        fiche = self.sudo()
        if not fiche.ev_nb_criteres:
            return
        est_colonne_agent = bool(
            phase.validator_id and phase.validator_id == fiche.employee_id)
        if est_colonne_agent:
            publiee, saisies = (self.employee_feedback_published,
                                fiche.ev_nb_notes_agent)
            quoi = _("votre auto-évaluation")
        else:
            publiee, saisies = (self.manager_feedback_published,
                                fiche.ev_nb_notes)
            quoi = _("votre notation")
        if publiee:
            return
        if saisies:
            motif = _(
                "Publiez d'abord %(quoi)s : vous avez apprécié "
                "%(nb)s critère(s) sur %(total)s, mais personne ne le voit "
                "encore. Une fois la phase validée, vous ne pourriez plus "
                "la publier.",
                quoi=quoi, nb=saisies, total=fiche.ev_nb_criteres)
        else:
            motif = _(
                "Vous n'avez apprécié aucun critère de la grille. "
                "Remplissez-la et publiez %(quoi)s avant de valider cette "
                "phase : sans cela, l'évaluation de %(agent)s partirait "
                "vide.",
                quoi=quoi, agent=fiche.employee_id.name or "")
        if self.env.user.has_group("hr_appraisal.group_hr_appraisal_user"):
            self.message_post(body=_(
                "Phase « %(phase)s » validée par le service RH SANS "
                "publication de la notation. %(motif)s",
                phase=phase.name, motif=motif))
            return
        raise UserError(motif)

    def _ev_cloturer(self):
        """Toutes les phases traitées : l'évaluation est faite.

        On écrit directement l'état final, sans passer par « Confirmé » :
        cette bascule déclencherait les e-mails du standard, qui n'ont pas
        lieu d'être une fois le circuit terminé.
        """
        self.ensure_one()
        # Une évaluation SANS AUCUNE note du responsable n'est pas une
        # évaluation faite : c'est un dossier resté sans évaluateur. Le cas
        # se produit quand la fiche de l'agent n'a pas de supérieur
        # renseigné — les phases du N+1 et du N+2 sont alors sautées au
        # lancement, et il ne reste que l'auto-évaluation. La publier
        # clôturait tout, et le dossier s'affichait « Terminée » avec une
        # note officielle de zéro. On refuse : le dossier reste ouvert, le
        # service RH est prévenu, et il désignera un évaluateur.
        if self.sudo().ev_grille_id and not self.sudo().ev_nb_notes:
            self.message_post(body=_(
                "Circuit terminé, mais AUCUNE notation n'a été portée par "
                "un responsable : l'évaluation de %s reste ouverte. Le "
                "service RH doit lui désigner un évaluateur, puis relancer "
                "la phase de notation.", self.sudo().employee_id.name or ""))
            return
        if self.state != "done":
            # Contexte : c'est le circuit lui-même qui clôture, le verrou de
            # write() ne doit pas s'y opposer.
            self.with_context(ev_cloture_circuit=True).write({"state": "done"})
        self.message_post(body=_(
            "Circuit d'évaluation terminé — évaluation clôturée."))

    def action_ev_renvoyer(self, comment=None):
        """Renvoie la phase en cours à la phase précédente, pour correction.
        Le commentaire est obligatoire : il dit ce qui doit être corrigé."""
        for appraisal in self:
            phase = appraisal._ev_check_droits()
            if not (comment and comment.strip()):
                raise UserError(_(
                    "Précisez ce qui doit être corrigé : le commentaire est "
                    "obligatoire pour un renvoi."))
            precedentes = appraisal.ev_etape_ids.filtered(
                lambda e: e.state == "done" and e.sequence <= phase.sequence)
            cible = precedentes.sorted(
                key=lambda e: (e.sequence, e.id), reverse=True)[:1]
            if not cible:
                raise UserError(_(
                    "La phase « %s » est la première du circuit : il n'y a "
                    "aucune étape antérieure vers laquelle renvoyer.",
                    phase.name))
            phase.sudo().state = "waiting"
            cible.sudo().write({
                "state": "pending",
                "comment": comment,
                "acted_by_id": self.env.uid,
                "date_action": fields.Datetime.now(),
            })
            rouverte = appraisal._ev_rouvrir_colonne(cible)
            appraisal.message_post(body=_(
                "Phase « %(phase)s » renvoyée à « %(cible)s » par %(user)s. "
                "Motif : %(motif)s%(rouvert)s",
                phase=phase.name, cible=cible.name,
                user=self.env.user.name, motif=comment,
                rouvert=(_(" La %s a été rouverte pour correction.", rouverte)
                         if rouverte else "")))

    def _ev_rouvrir_colonne(self, cible):
        """Rouvre la colonne de notation que la phase visée doit corriger.

        Sans cela, renvoyer un dossier le condamnait : la phase repartait
        bien vers son acteur, mais sa colonne était PUBLIÉE, donc figée.
        L'acteur n'avait plus aucun bouton, et celui qui avait renvoyé ne
        pouvait plus rien faire non plus — un clic suffisait à bloquer
        définitivement l'évaluation.

        Renvoyer pour correction, c'est demander une correction : la
        colonne concernée doit redevenir modifiable. Elle sera republiée
        par son auteur, ce qui fera repartir le circuit.

        Retourne le libellé de la colonne rouverte, ou None.
        """
        self.ensure_one()
        if not cible.saisie_notation:
            return None
        fiche = self.sudo()
        est_colonne_agent = bool(
            cible.validator_id and cible.validator_id == fiche.employee_id)
        champ = ("employee_feedback_published" if est_colonne_agent
                 else "manager_feedback_published")
        if not fiche[champ]:
            return None
        # Odoo réserve l'écriture de ces drapeaux à l'auteur de la colonne
        # (`hr.appraisal._check_access`). Or ici ce n'est pas un auteur qui
        # écrit : c'est LE CIRCUIT qui rouvre, à la demande de celui qui
        # renvoie. On le dit explicitement, comme pour la génération des
        # lignes de notation au lancement d'une campagne.
        fiche.with_context(ev_reouverture_circuit=True).write({champ: False})
        return (_("auto-évaluation") if est_colonne_agent
                else _("notation du responsable"))

    def _check_access(self, fields):
        """Laisse passer les réouvertures décidées par le circuit.

        Le garde-fou d'Odoo protège les feedbacks contre l'écriture par un
        tiers — règle saine, qu'on ne lève QUE sur demande explicite de
        notre propre code, jamais sur `sudo()`.
        """
        if self.env.context.get("ev_reouverture_circuit"):
            return
        return super()._check_access(fields)
