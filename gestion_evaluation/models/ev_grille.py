# -*- coding: utf-8 -*-
"""Grille d'évaluation : la fiche d'appréciation de la banque, à l'écran.

Trois niveaux, ni plus ni moins, calqués sur le document réel :

    BLOC        Savoir-faire
      THÈME       Performance dans son poste
        CRITÈRE     Qualité du travail fourni      <- on note ici
        CRITÈRE     Respect des délais

La note remonte par MOYENNES SIMPLES, exactement comme les formules du
fichier Excel de la BADF :
    note d'un thème  = moyenne de ses critères notés
    note d'un bloc   = moyenne de ses thèmes notés
    note globale     = moyenne des blocs notés
Aucune pondération : la banque n'en utilise pas.
"""
from markupsafe import Markup, escape

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


def _moyenne(valeurs):
    """Moyenne des valeurs renseignées, None s'il n'y en a aucune."""
    valeurs = [v for v in valeurs if v is not None]
    return (sum(valeurs) / len(valeurs)) if valeurs else None


class EvEchelleNiveau(models.Model):
    """Échelle de notation : les niveaux proposés à l'évaluateur.

    Cinq niveaux à la BADF (« Point d'amélioration prioritaire » = 1 à
    « Excellence » = 5), mais le nombre et les libellés sont libres. La
    VALEUR du niveau est recopiée sur la note au moment de la saisie :
    modifier l'échelle ensuite ne réécrit jamais une notation déjà faite.
    """
    _name = "ev.echelle.niveau"
    _description = "Niveau de l'échelle de notation"
    _order = "sequence, valeur, id"

    sequence = fields.Integer(string="Ordre", default=10)
    name = fields.Char(string="Niveau", required=True)
    valeur = fields.Float(string="Note correspondante", required=True)
    active = fields.Boolean(default=True)

    @api.constrains("valeur")
    def _check_valeur(self):
        for niveau in self:
            if niveau.valeur < 0:
                raise ValidationError(_(
                    "La note d'un niveau ne peut pas être négative."))

    # --- Photographie : l'échelle figée d'une campagne lancée ------------
    # Même règle que pour la grille. La VALEUR d'un niveau était déjà
    # recopiée sur la note à la saisie — modifier l'échelle ne réécrivait
    # donc aucune note. Mais le LIBELLÉ, lui, était lu vif : renommer
    # « Excellence » changeait le mot lu sur les évaluations passées.
    # Une campagne lancée emporte donc aussi sa copie de l'échelle.
    campagne_photo_id = fields.Many2one(
        "ev.campagne", string="Campagne photographiée",
        readonly=True, copy=False, ondelete="cascade", index=True,
        help="Renseigné sur les COPIES figées. Un niveau photographié "
             "appartient à sa campagne et ne se modifie plus.")
    modele_id = fields.Many2one(
        "ev.echelle.niveau", string="Copié de", readonly=True, copy=False)
    est_photo = fields.Boolean(
        string="Niveau figé", compute="_compute_est_photo", store=True)

    @api.depends("campagne_photo_id")
    def _compute_est_photo(self):
        for niveau in self:
            niveau.est_photo = bool(niveau.campagne_photo_id)

    @api.model
    def _ev_photographier(self, campagne):
        """Copie figée de l'échelle courante, rattachée à la campagne.

        Retourne ``(niveaux_copies, correspondance)``.
        """
        Niveau = self.sudo().with_context(ev_photo_campagne=True)
        correspondance = {}
        copies = Niveau.browse()
        for niveau in Niveau.search([("campagne_photo_id", "=", False)],
                                    order="sequence, valeur, id"):
            copie = Niveau.create({
                "name": niveau.name,
                "valeur": niveau.valeur,
                "sequence": niveau.sequence,
                "campagne_photo_id": campagne.id,
                "modele_id": niveau.id,
            })
            correspondance[niveau.id] = copie
            copies |= copie
        return copies, correspondance

    def _ev_check_photo(self, operation):
        """Un niveau figé ne se retouche pas."""
        if self.env.context.get("ev_photo_campagne"):
            return
        for niveau in self:
            if not niveau.campagne_photo_id:
                continue
            raise UserError(_(
                "« %(niveau)s » appartient à l'échelle figée de la campagne "
                "« %(campagne)s » : elle ne se %(op)s pas.\n\n"
                "Une campagne lancée garde l'échelle qu'elle a "
                "photographiée — c'est ce qui garantit qu'une note gardera "
                "le même libellé dans dix ans. Modifiez l'échelle de "
                "référence : les campagnes suivantes en profiteront.",
                niveau=niveau.name or "", op=operation,
                campagne=niveau.campagne_photo_id.name or ""))

    def write(self, vals):
        if set(vals) - {"active"}:
            self._ev_check_photo(_("modifie"))
        return super().write(vals)

    def unlink(self):
        self._ev_check_photo(_("supprime"))
        return super().unlink()

    def name_get(self):
        return [(n.id, "%s (%g)" % (n.name, n.valeur)) for n in self]


class EvGrille(models.Model):
    _name = "ev.grille"
    _description = "Grille d'évaluation"
    _order = "name"

    name = fields.Char(string="Intitulé", required=True)
    description = fields.Text(string="Note d'usage")
    company_id = fields.Many2one(
        "res.company", string="Société",
        help="Vide = grille commune à toutes les sociétés.")
    active = fields.Boolean(default=True)

    bloc_ids = fields.One2many(
        "ev.grille.bloc", "grille_id", string="Blocs")
    theme_ids = fields.One2many(
        "ev.grille.theme", "grille_id", string="Thèmes")
    critere_ids = fields.One2many(
        "ev.grille.critere", "grille_id", string="Critères",
        help="Tous les critères de la grille, à plat : la façon la plus "
             "rapide d'en ajouter ou d'en retirer.")
    apercu = fields.Html(
        string="Aperçu", compute="_compute_apercu", sanitize=False)
    nb_criteres = fields.Integer(
        string="Nombre de critères", compute="_compute_nb_criteres")
    campagne_ids = fields.One2many(
        "ev.campagne", "grille_id", string="Campagnes")

    # --- Photographie : la grille figée d'une campagne lancée -------------
    # Le circuit est photographié au lancement (``ev.evaluation.etape``).
    # La grille ne l'était pas : elle restait lue VIVE, si bien que
    # retoucher la grille de référence — déplacer un critère d'un thème à
    # l'autre, en ajouter un, en renommer un — modifiait les évaluations
    # DÉJÀ EN COURS. Les moyennes bougeaient sous les yeux des évaluateurs.
    #
    # Au lancement, la campagne emporte donc sa propre copie, figée. Le
    # service RH modifie librement la grille de référence : seules les
    # campagnes SUIVANTES en profitent.
    campagne_photo_id = fields.Many2one(
        "ev.campagne", string="Campagne photographiée",
        readonly=True, copy=False, ondelete="cascade", index=True,
        help="Renseigné sur les COPIES figées. Une grille photographiée "
             "appartient à sa campagne et ne se modifie plus.")
    modele_id = fields.Many2one(
        "ev.grille", string="Copiée de", readonly=True, copy=False,
        help="Grille de référence dont cette photographie est issue.")
    est_photo = fields.Boolean(
        string="Grille figée", compute="_compute_est_photo", store=True)

    @api.depends("campagne_photo_id")
    def _compute_est_photo(self):
        for grille in self:
            grille.est_photo = bool(grille.campagne_photo_id)

    def _ev_photographier(self, campagne):
        """Copie figée de la grille, rattachée à la campagne.

        Copie EXPLICITE plutôt que ``copy()`` : on a besoin de la
        correspondance ancien critère → nouveau, pour rebrancher les
        notations existantes lors de la reprise des campagnes déjà
        lancées.

        Retourne ``(photo, correspondance)``.
        """
        self.ensure_one()
        contexte = {"ev_photo_campagne": True}
        Grille = self.env["ev.grille"].sudo().with_context(**contexte)
        Bloc = self.env["ev.grille.bloc"].sudo().with_context(**contexte)
        Theme = self.env["ev.grille.theme"].sudo().with_context(**contexte)
        Critere = self.env["ev.grille.critere"].sudo().with_context(**contexte)

        photo = Grille.create({
            "name": _("%(grille)s — %(campagne)s",
                      grille=self.name or "", campagne=campagne.name or ""),
            "description": self.description,
            "company_id": self.company_id.id,
            "campagne_photo_id": campagne.id,
            "modele_id": self.id,
        })
        correspondance = {}
        for bloc in self.bloc_ids:
            copie_bloc = Bloc.create({
                "grille_id": photo.id,
                "name": bloc.name,
                "sequence": bloc.sequence,
            })
            for theme in bloc.theme_ids:
                copie_theme = Theme.create({
                    "bloc_id": copie_bloc.id,
                    "name": theme.name,
                    "sequence": theme.sequence,
                })
                for critere in theme.critere_ids:
                    correspondance[critere.id] = Critere.create({
                        "theme_id": copie_theme.id,
                        "name": critere.name,
                        "description": critere.description,
                        "sequence": critere.sequence,
                    })
        return photo, correspondance

    # --- Verrou : une photographie ne se retouche pas --------------------
    def _ev_check_photo(self, operation):
        """Refuse de toucher à une grille figée.

        Le verrou est au niveau du MODÈLE : masquer les boutons dans la
        vue n'empêcherait ni l'import, ni l'appel direct. Seule la copie
        elle-même se lève le verrou, par un contexte explicite.
        """
        if self.env.context.get("ev_photo_campagne"):
            return
        for grille in self:
            if not grille.campagne_photo_id:
                continue
            raise UserError(_(
                "« %(grille)s » est la grille figée de la campagne "
                "« %(campagne)s » : elle ne se %(op)s pas.\n\n"
                "Une campagne lancée garde la grille qu'elle a "
                "photographiée — c'est ce qui garantit que les notes déjà "
                "portées gardent le même sens. Modifiez la grille de "
                "référence « %(modele)s » : les campagnes suivantes en "
                "profiteront.",
                grille=grille.name or "", op=operation,
                campagne=grille.campagne_photo_id.name or "",
                modele=grille.modele_id.name or _("d'origine")))

    def write(self, vals):
        # `active` reste permis : archiver une photo ne change rien aux
        # notes, et le service RH doit pouvoir ranger ses listes.
        if set(vals) - {"active"}:
            self._ev_check_photo(_("modifie"))
        return super().write(vals)

    def unlink(self):
        self._ev_check_photo(_("supprime"))
        return super().unlink()

    @api.depends("critere_ids")
    def _compute_nb_criteres(self):
        for grille in self:
            grille.nb_criteres = len(grille.critere_ids)

    @api.depends("bloc_ids.name", "bloc_ids.sequence",
                 "bloc_ids.theme_ids.name", "bloc_ids.theme_ids.sequence",
                 "bloc_ids.theme_ids.critere_ids.name",
                 "bloc_ids.theme_ids.critere_ids.sequence")
    def _compute_apercu(self):
        for grille in self:
            grille.apercu = grille._rendu_apercu()

    def _rendu_apercu(self):
        """La grille entière, lisible d'un coup d'œil — sans pourcentage :
        tous les critères d'un thème comptent pareil, tous les thèmes d'un
        bloc aussi, et les deux blocs pèsent autant l'un que l'autre."""
        self.ensure_one()
        if not self.bloc_ids:
            return Markup(
                '<p class="text-muted mb-0">Grille vide. Ajoutez vos blocs, '
                'leurs thèmes et leurs critères dans l\'onglet '
                '<b>Structure</b>.</p>')
        lignes = []
        for bloc in self.bloc_ids:
            lignes.append('<tr><td><b>%s</b></td></tr>' % escape(bloc.name or ""))
            for theme in bloc.theme_ids:
                lignes.append(
                    '<tr><td style="padding-left:2em"><i>%s</i></td></tr>'
                    % escape(theme.name or ""))
                for critere in theme.critere_ids:
                    lignes.append(
                        '<tr><td style="padding-left:4em">%s</td></tr>'
                        % escape(critere.name or ""))
        return Markup(
            '<table class="table table-sm" style="width:100%%">'
            '<tbody>%s</tbody>'
            '<tfoot><tr><td class="text-muted small">'
            'Note d\'un thème = moyenne de ses critères &nbsp;•&nbsp; '
            'note d\'un bloc = moyenne de ses thèmes &nbsp;•&nbsp; '
            'note globale = moyenne des blocs.</td></tr></tfoot>'
            '</table>' % "".join(lignes))

    def action_dupliquer(self):
        """Crée une copie modifiable, structure comprise."""
        self.ensure_one()
        copie = self.copy({"name": _("%s (copie)", self.name)})
        for bloc in self.bloc_ids:
            nouveau_bloc = bloc.copy({"grille_id": copie.id})
            nouveau_bloc.theme_ids.unlink()
            for theme in bloc.theme_ids:
                nouveau_theme = theme.copy({"bloc_id": nouveau_bloc.id})
                nouveau_theme.critere_ids.unlink()
                for critere in theme.critere_ids:
                    critere.copy({"theme_id": nouveau_theme.id})
        return {
            "type": "ir.actions.act_window",
            "res_model": "ev.grille",
            "res_id": copie.id,
            "view_mode": "form",
        }

    def _score(self, notes):
        """Note globale : moyenne des blocs notés.

        ``notes`` : {id de critère: valeur}. Les critères non notés sont
        simplement ignorés — ils ne tirent pas la note vers le bas.
        """
        self.ensure_one()
        return _moyenne([bloc._score(notes) for bloc in self.bloc_ids])


class EvGrilleBloc(models.Model):
    """Grande partie de la fiche : « Savoir-faire », « Savoir-être »...
    Les blocs s'ajoutent et se retirent librement."""
    _name = "ev.grille.bloc"
    _description = "Bloc d'une grille d'évaluation"
    _order = "sequence, id"

    grille_id = fields.Many2one(
        "ev.grille", string="Grille", required=True, ondelete="cascade",
        index=True)
    sequence = fields.Integer(string="Ordre", default=10)
    name = fields.Char(string="Bloc", required=True)
    theme_ids = fields.One2many(
        "ev.grille.theme", "bloc_id", string="Thèmes")
    nb_criteres = fields.Integer(
        string="Critères", compute="_compute_nb_criteres")

    @api.depends("theme_ids.critere_ids")
    def _compute_nb_criteres(self):
        for bloc in self:
            bloc.nb_criteres = len(bloc.theme_ids.critere_ids)

    @api.model
    def _ev_grilles_visees(self, vals_list):
        ids = [v["grille_id"] for v in vals_list if v.get("grille_id")]
        return self.env["ev.grille"].browse(ids)

    # Une grille figée ne se retouche pas, à aucun de ses étages.
    @api.model_create_multi
    def create(self, vals_list):
        self._ev_grilles_visees(vals_list)._ev_check_photo(_("complète"))
        return super().create(vals_list)

    def write(self, vals):
        self.mapped("grille_id")._ev_check_photo(_("modifie"))
        cibles = self._ev_grilles_visees([vals])
        if cibles:
            cibles._ev_check_photo(_("complète"))
        return super().write(vals)

    def unlink(self):
        self.mapped("grille_id")._ev_check_photo(_("modifie"))
        return super().unlink()

    def _score(self, notes):
        self.ensure_one()
        return _moyenne([theme._score(notes) for theme in self.theme_ids])


class EvGrilleTheme(models.Model):
    """Regroupement de critères à l'intérieur d'un bloc : « Qualités
    relationnelles », « Autonomie »... Un bloc peut n'en avoir qu'un."""
    _name = "ev.grille.theme"
    _description = "Thème d'une grille d'évaluation"
    _order = "bloc_sequence, sequence, id"

    bloc_id = fields.Many2one(
        "ev.grille.bloc", string="Bloc", required=True, ondelete="cascade",
        index=True)
    grille_id = fields.Many2one(
        related="bloc_id.grille_id", store=True, index=True)
    bloc_sequence = fields.Integer(
        related="bloc_id.sequence", store=True, index=True)
    sequence = fields.Integer(string="Ordre", default=10)
    name = fields.Char(string="Thème", required=True)
    critere_ids = fields.One2many(
        "ev.grille.critere", "theme_id", string="Critères")
    nb_criteres = fields.Integer(
        string="Critères", compute="_compute_nb_criteres")

    @api.depends("critere_ids")
    def _compute_nb_criteres(self):
        for theme in self:
            theme.nb_criteres = len(theme.critere_ids)

    @api.model
    def _ev_grilles_visees(self, vals_list):
        ids = [v["bloc_id"] for v in vals_list if v.get("bloc_id")]
        return self.env["ev.grille.bloc"].browse(ids).mapped("grille_id")
    # Une grille figée ne se retouche pas, à aucun de ses étages.
    @api.model_create_multi
    def create(self, vals_list):
        self._ev_grilles_visees(vals_list)._ev_check_photo(_("complète"))
        return super().create(vals_list)

    def write(self, vals):
        self.mapped("grille_id")._ev_check_photo(_("modifie"))
        cibles = self._ev_grilles_visees([vals])
        if cibles:
            cibles._ev_check_photo(_("complète"))
        return super().write(vals)

    def unlink(self):
        self.mapped("grille_id")._ev_check_photo(_("modifie"))
        return super().unlink()

    def name_get(self):
        return [(t.id, "%s / %s" % (t.bloc_id.name or "", t.name or ""))
                for t in self]

    def _score(self, notes):
        self.ensure_one()
        return _moyenne([notes.get(c.id) for c in self.critere_ids])


class EvGrilleCritere(models.Model):
    """Ligne notée par l'évaluateur.

    Un critère déjà noté ne se supprime pas : les notations le
    référencent (``ondelete="restrict"``). La base le refusait déjà, mais
    par une erreur technique illisible — voir ``_check_critere_note``.
    """
    _name = "ev.grille.critere"
    _description = "Critère d'une grille d'évaluation"
    _order = "bloc_sequence, theme_sequence, sequence, id"

    theme_id = fields.Many2one(
        "ev.grille.theme", string="Thème", required=True,
        ondelete="cascade", index=True)
    bloc_id = fields.Many2one(
        related="theme_id.bloc_id", store=True, index=True)
    grille_id = fields.Many2one(
        related="theme_id.grille_id", store=True, index=True)
    bloc_sequence = fields.Integer(
        related="theme_id.bloc_sequence", store=True, index=True)
    theme_sequence = fields.Integer(
        related="theme_id.sequence", store=True, index=True)
    sequence = fields.Integer(string="Ordre", default=10)
    name = fields.Char(string="Critère", required=True)
    description = fields.Char(
        string="Précision",
        help="Aide affichée à l'évaluateur pour cadrer son appréciation.")

    @api.model
    def _ev_grilles_visees(self, vals_list):
        ids = [v["theme_id"] for v in vals_list if v.get("theme_id")]
        return self.env["ev.grille.theme"].browse(ids).mapped("grille_id")
    # Une grille figée ne se retouche pas, à aucun de ses étages.
    @api.model_create_multi
    def create(self, vals_list):
        self._ev_grilles_visees(vals_list)._ev_check_photo(_("complète"))
        return super().create(vals_list)

    def write(self, vals):
        self.mapped("grille_id")._ev_check_photo(_("modifie"))
        cibles = self._ev_grilles_visees([vals])
        if cibles:
            cibles._ev_check_photo(_("complète"))
        return super().write(vals)

    def unlink(self):
        self.mapped("grille_id")._ev_check_photo(_("modifie"))
        return super().unlink()

    def name_get(self):
        return [(c.id, c.name or "") for c in self]

    @api.ondelete(at_uninstall=False)
    def _check_critere_note(self):
        """Explique le refus au lieu de laisser remonter l'erreur SQL.

        Supprimer un critère déjà noté effacerait des appréciations
        portées sur des dossiers d'agents. La base l'interdit déjà ; le
        service RH méritait de savoir pourquoi, sur combien
        d'évaluations, et quoi faire à la place.
        """
        Ligne = self.env["ev.notation.ligne"].sudo()
        for critere in self:
            lignes = Ligne.search([("critere_id", "=", critere.id)])
            if not lignes:
                continue
            evaluations = lignes.mapped("appraisal_id")
            noms = evaluations.mapped("employee_id.name")[:3]
            raise UserError(_(
                "Le critère « %(critere)s » est déjà noté sur "
                "%(nb)s évaluation(s) (%(qui)s%(suite)s) : le supprimer "
                "effacerait des appréciations portées au dossier de ces "
                "agents.\n\n"
                "Pour ne plus l'utiliser dans les campagnes à venir, "
                "retirez-le de la grille en créant une nouvelle version, "
                "ou renommez-le. Les évaluations déjà lancées gardent la "
                "grille qu'elles ont photographiée.",
                critere=critere.name or "", nb=len(evaluations),
                qui=", ".join(n for n in noms if n),
                suite=_(", …") if len(evaluations) > 3 else ""))
