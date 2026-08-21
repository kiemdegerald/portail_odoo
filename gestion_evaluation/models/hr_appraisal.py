# -*- coding: utf-8 -*-
"""Rattachement à la campagne, et circuit de validation à plusieurs phases.

Le module ne modifie AUCUN comportement natif de ``hr.appraisal`` : les
feedbacks, la notation, les compétences, l'entretien et le 360° restent ceux
d'Odoo. Il ajoute par-dessus le circuit que le standard n'a pas — notamment
la **validation N+2** exigée par le TDR.
"""
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
    def _ev_est_agent(self):
        """L'utilisateur courant est-il l'agent évalué ?"""
        self.ensure_one()
        return bool(self.employee_id
                    and self.employee_id.user_id == self.env.user)

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
                self.employee_id.name or "")
        if self.state == "cancel":
            return _(
                "L'évaluation de %s est annulée : sa notation ne se modifie "
                "plus.", self.employee_id.name or "")

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
        if colonne == "agent" and not self._ev_est_agent():
            return _(
                "L'auto-évaluation appartient à %s : vous ne pouvez pas la "
                "remplir à sa place.", self.employee_id.name or "")
        if colonne == "manager" and self._ev_est_agent():
            return _(
                "La note du manager ne se saisit pas par l'agent évalué. "
                "Remplissez votre auto-évaluation.")
        phase = self.ev_phase_courante_id
        if not phase:
            return _(
                "Aucune phase du circuit n'est en cours sur cette "
                "évaluation : seul le service RH peut intervenir.")
        if not self.ev_can_agir:
            attendu = (phase.validator_id.name if phase.validator_id
                       else _("le service RH"))
            return _(
                "La phase « %(phase)s » attend l'action de %(qui)s : vous ne "
                "pouvez pas saisir la notation.",
                phase=phase.name, qui=attendu)
        if not phase.saisie_notation:
            return _(
                "La phase « %(phase)s » ne donne pas accès à la grille de "
                "notation : elle se valide ou se renvoie, elle ne se note "
                "pas.", phase=phase.name)
        return None

    @api.depends_context("uid")
    @api.depends("state", "ev_phase_courante_id", "ev_can_agir",
                 "employee_feedback_published", "manager_feedback_published")
    def _compute_ev_notation_modifiable(self):
        for appraisal in self:
            appraisal.ev_notation_modifiable = not \
                appraisal._ev_motif_notation_fermee(colonne="manager")
            appraisal.ev_auto_modifiable = not \
                appraisal._ev_motif_notation_fermee(colonne="agent")

    @api.depends_context("uid")
    @api.depends("employee_feedback_published", "manager_feedback_published",
                 "employee_id")
    def _compute_ev_visibilite(self):
        """Qui voit quoi : chacun voit toujours SA colonne ; celle de
        l'autre n'apparaît qu'une fois publiée. Les RH voient tout — ils
        instruisent le dossier."""
        est_rh = self.env.user.has_group(
            "hr_appraisal.group_hr_appraisal_user")
        for appraisal in self:
            est_agent = appraisal._ev_est_agent()
            appraisal.ev_voir_notes_agent = bool(
                est_rh or est_agent or appraisal.employee_feedback_published)
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
                 "ev_grille_id.theme_ids.bloc_id")
    def _compute_ev_notation(self):
        """Deux notes, même calcul : celle du manager fait foi, celle de
        l'agent sert de comparaison."""
        for appraisal in self:
            lignes = appraisal.ev_note_ids
            grille = appraisal.ev_grille_id
            notees = lignes.filtered(lambda l: l.niveau_manager_id)
            auto = lignes.filtered(lambda l: l.niveau_agent_id)
            appraisal.ev_nb_criteres = len(lignes)
            appraisal.ev_nb_notes = len(notees)
            appraisal.ev_nb_notes_agent = len(auto)
            appraisal.ev_notation_complete = bool(
                lignes and len(notees) == len(lignes))
            appraisal.ev_agent_complete = bool(
                lignes and len(auto) == len(lignes))
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
            grille = appraisal.ev_grille_id
            if not grille:
                appraisal.ev_notation_detail = False
                continue
            voir_agent = appraisal.ev_voir_notes_agent
            voir_manager = appraisal.ev_voir_notes_manager
            notes_agent = {l.critere_id.id: l.valeur_agent
                           for l in appraisal.ev_note_ids if l.niveau_agent_id}
            notes_manager = {l.critere_id.id: l.valeur_manager
                             for l in appraisal.ev_note_ids
                             if l.niveau_manager_id}

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
        Ligne = self.env["ev.notation.ligne"].sudo()
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

    @api.depends("employee_id", "ev_campagne_id")
    def _compute_ev_objectifs(self):
        Goal = self.env["hr.appraisal.goal"]
        for appraisal in self:
            if appraisal.ev_campagne_id and appraisal.employee_id:
                objectifs = Goal.search([
                    ("employee_id", "=", appraisal.employee_id.id),
                    ("ev_campagne_id", "=", appraisal.ev_campagne_id.id),
                ])
            else:
                objectifs = Goal
            appraisal.ev_objectif_ids = objectifs
            appraisal.ev_objectif_count = len(objectifs)

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

    @api.depends_context("uid")
    @api.depends("ev_phase_courante_id", "ev_acteur_courant_id")
    def _compute_ev_can_agir(self):
        user_employee = self.env.user.employee_id
        is_rh = self.env.user.has_group("hr_appraisal.group_hr_appraisal_user")
        for appraisal in self:
            phase = appraisal.ev_phase_courante_id
            if not phase:
                appraisal.ev_can_agir = False
                continue
            # Phase confiée au service RH : tout gestionnaire peut agir.
            if phase.acteur == "rh":
                appraisal.ev_can_agir = is_rh
                continue
            appraisal.ev_can_agir = bool(
                is_rh or (user_employee and user_employee == phase.validator_id))

    # ------------------------------------------------------------------
    # Verrou : le circuit prime sur la clôture directe
    # ------------------------------------------------------------------
    def _ev_message_circuit_ouvert(self):
        """Message expliquant ce qui reste à faire avant de clôturer."""
        self.ensure_one()
        restantes = self.ev_etape_ids.filtered(
            lambda e: e.state in ("waiting", "pending"))
        courante = self.ev_phase_courante_id
        attendu = (courante.validator_id.name if courante.validator_id
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
        return super().write(vals)

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
                lignes.append({
                    "appraisal_id": appraisal.id,
                    "sequence": phase.sequence,
                    "name": phase.name,
                    "acteur": phase.acteur,
                    "saisie_notation": phase.saisie_notation,
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
        phase = self.ev_phase_courante_id
        if not phase:
            raise UserError(_(
                "Cette évaluation n'a aucune phase en attente."))
        if not self.ev_can_agir:
            attendu = phase.validator_id.name if phase.validator_id \
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
        if self.ev_grille_id:
            manquants = (self.ev_nb_criteres
                         - (self.ev_nb_notes_agent if colonne == "agent"
                            else self.ev_nb_notes))
            if manquants > 0:
                raise UserError(_(
                    "Il reste %(nb)s critère(s) à apprécier sur %(total)s. "
                    "Complétez la grille avant de publier.",
                    nb=manquants, total=self.ev_nb_criteres))
        champ = ("employee_feedback_published" if colonne == "agent"
                 else "manager_feedback_published")
        self.sudo().write({champ: True})
        self.message_post(body=(
            _("Auto-évaluation publiée par %s.", self.env.user.name)
            if colonne == "agent"
            else _("Notation publiée par %s.", self.env.user.name)))

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
            suivante = appraisal.ev_etape_ids.filtered(
                lambda e: e.state == "waiting")[:1]
            if suivante:
                suivante.sudo().state = "pending"
            else:
                appraisal._ev_cloturer()

    def _ev_cloturer(self):
        """Toutes les phases traitées : l'évaluation est faite.

        On écrit directement l'état final, sans passer par « Confirmé » :
        cette bascule déclencherait les e-mails du standard, qui n'ont pas
        lieu d'être une fois le circuit terminé.
        """
        self.ensure_one()
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
            appraisal.message_post(body=_(
                "Phase « %(phase)s » renvoyée à « %(cible)s » par %(user)s. "
                "Motif : %(motif)s",
                phase=phase.name, cible=cible.name,
                user=self.env.user.name, motif=comment))
