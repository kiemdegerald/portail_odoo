# -*- coding: utf-8 -*-
"""Les campagnes déjà lancées retrouvent les sections de leur grille.

Une campagne photographie sa grille au lancement. Les campagnes lancées
avant que la grille ne porte un poids et un type par section ont donc
une photographie sans ces deux informations : leurs sections pèsent
0 %, la section « Objectifs » — qui n'a aucun critère — n'a même pas été
recopiée, et la note globale de ces évaluations vaut zéro.

On resynchronise la photographie sur sa grille de référence, sans jamais
toucher à ce qui a déjà été noté : seules les sections SANS critère sont
recréées ; une section notée absente de la photographie est signalée
dans le journal, pas fabriquée — la recréer donnerait des critères sans
ligne de notation, donc des notes fantômes.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Bloc = env["ev.grille.bloc"].with_context(ev_photo_campagne=True)
    campagnes = env["ev.campagne"].search([
        ("grille_photo_id", "!=", False),
        ("grille_id", "!=", False),
    ])
    recreees = synchronisees = 0
    for campagne in campagnes:
        photo = campagne.grille_photo_id
        par_nom = {bloc.name: bloc for bloc in photo.bloc_ids}
        for bloc in campagne.grille_id.bloc_ids:
            cible = par_nom.get(bloc.name)
            if not cible:
                if bloc.theme_ids.critere_ids:
                    _logger.warning(
                        "Campagne « %s » : la section notée « %s » manque à "
                        "la grille figée ; elle n'est pas recréée pour ne "
                        "pas inventer de notes.", campagne.name, bloc.name)
                    continue
                Bloc.create({
                    "grille_id": photo.id,
                    "name": bloc.name,
                    "sequence": bloc.sequence,
                    "poids": bloc.poids,
                    "type_section": bloc.type_section,
                })
                recreees += 1
            elif (cible.poids != bloc.poids
                  or cible.type_section != bloc.type_section):
                cible.with_context(ev_photo_campagne=True).write({
                    "poids": bloc.poids,
                    "type_section": bloc.type_section,
                })
                synchronisees += 1
    _logger.info(
        "Grilles figées : %s section(s) recréée(s), %s section(s) "
        "resynchronisée(s) sur %s campagne(s).",
        recreees, synchronisees, len(campagnes))
