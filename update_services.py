with open('src/ffbb_mcp/services.py', 'r') as f:
    content = f.read()

content = content.replace('''
            if str_my_eng and (str_my_eng in (id_eng1, id_eng2)):
                is_my_team = True
            else:
                is_my_team = _match_team_name(
                    str(m.get("nomEquipe1", "")),
                    str(organisme_nom),
                    numero_equipe_match,
                ) or _match_team_name(
                    str(m.get("nomEquipe2", "")),
                    str(organisme_nom),
                    numero_equipe_match,
                )
''', '''
            if str_my_eng and (str_my_eng in (id_eng1, id_eng2)):
                is_my_team = True
            else:
                organisme_nom_norm = _normalize_name(str(organisme_nom))
                is_my_team = _match_team_name(
                    str(m.get("nomEquipe1", "")),
                    organisme_nom_norm,
                    numero_equipe_match,
                    is_organisme_nom_normalized=True
                ) or _match_team_name(
                    str(m.get("nomEquipe2", "")),
                    organisme_nom_norm,
                    numero_equipe_match,
                    is_organisme_nom_normalized=True
                )
''')

content = content.replace('''
def _match_team_name(
    nom_equipe_rencontre: str, organisme_nom: str, numero_equipe: int | None
) -> bool:
''', '''
def _match_team_name(
    nom_equipe_rencontre: str, organisme_nom: str, numero_equipe: int | None,
    is_organisme_nom_normalized: bool = False
) -> bool:
''')

content = content.replace('''
    nom_norm = _normalize_name(nom_equipe_rencontre)
    club_norm = _normalize_name(organisme_nom)
    if not nom_norm or not club_norm:
''', '''
    nom_norm = _normalize_name(nom_equipe_rencontre)
    club_norm = organisme_nom if is_organisme_nom_normalized else _normalize_name(organisme_nom)
    if not nom_norm or not club_norm:
''')

with open('src/ffbb_mcp/services.py', 'w') as f:
    f.write(content)
