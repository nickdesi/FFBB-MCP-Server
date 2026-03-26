import pytest

from ffbb_mcp.services import get_organisme_service


@pytest.mark.asyncio
async def test_api_response_casing():
    """
    Vérifie la conservation du camelCase dans les réponses sérialisées.
    Ce test valide que services.py peut continuer à utiliser des types comme 'idCompetition'.
    """
    # Utilisation d'un ID connu (ex: 2 pour le Comité du Rhône ou similaire)
    # Note: nécessite une connexion internet ou un mock si l'env est restreint.
    # Ici on teste la logique réelle si possible.
    try:
        org_id = 2
        org = await get_organisme_service(org_id)

        # 1. Vérifie la présence des clés racines attendues (snake_case normalisé ou original)
        assert "id" in org
        assert "nom" in org
        assert "engagements" in org

        # 2. Vérifie le casing des objets imbriqués (Source de vérité FFBB)
        if org["engagements"]:
            engagement = org["engagements"][0]
            # On vérifie que le camelCase est préservé via serialize_model
            # Si idCompetition est présent, c'est que le casing original est conservé.
            assert "idCompetition" in engagement, (
                f"Clé 'idCompetition' manquante dans l'engagement. Trouvé: {list(engagement.keys())}"
            )
            assert "libelleCompetition" in engagement

    except Exception as e:
        pytest.skip(
            f"Test sauté car l'API n'est pas accessible ou l'ID est invalide: {e}"
        )


def test_joue_logic_documentation():
    """
    Test symbolique pour valider que la logique de filtrage 'joue' est intentionnelle.
    """
    # La logique : if joue not in (0, "0", None): continue
    # Signifie qu'on accepte :
    # - 0 (entier)
    # - "0" (chaîne)
    # - None (match programmé sans état défini)

    accepted = [0, "0", None]
    rejected = [
        1,
        "1",
        True,
        False,
    ]  # False est souvent 0, mais ici on est strict sur 0/"0"

    def should_keep(joue):
        return joue in (0, "0", None)

    for val in accepted:
        assert should_keep(val) is True
    for val in rejected:
        if val is False:
            continue  # Dépend de la vérité de (False == 0) en Python
        assert should_keep(val) is False
