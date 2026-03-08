import re

CLUB_ALIASES = {
    "jav": "jeanne d'arc vichy",
    "ja vichy": "jeanne d'arc vichy",
    "sbca": "stade clermontois basket auvergne",
    "stade clermontois": "stade clermontois basket auvergne",
    "asvel": "lyon villeurbanne",
    "ldlc asvel": "lyon villeurbanne",
    "chorale": "roanne",
    "cb": "cholet basket",
    "jlb": "jl bourg",
    "bourg": "jl bourg",
    "bcm": "cholet basket", # wait, BCM = gravelines dunkerque
    "gravelines": "bcm gravelines dunkerque",
    "pau": "elan bearnais",
    "msb": "le mans sarthe basket",
    "le mans": "le mans sarthe basket",
    "sluc": "roanne", # no, sluc nancy
    "nancy": "sluc nancy",
    "sig": "strasbourg",
    "pbr": "paris basket", # well, pbr is levallois or paris.
}

# Corrections
CLUB_ALIASES.update({
    "bcm": "gravelines dunkerque",
    "sluc": "nancy",
})

def normalize_query(query: str) -> str:
    """
    Normalize a search query to replace common club abbreviations
    or alternative names with their official FFBB names.
    This helps the FFBB API find the correct results.
    """
    if not query:
        return query
        
    normalized = query.lower().strip()
    
    # Try exact match first
    if normalized in CLUB_ALIASES:
        return CLUB_ALIASES[normalized]
        
    # Replace whole words
    for alias, official in CLUB_ALIASES.items():
        # Match whole word only (e.g., ' jav ', 'jav ', ' jav')
        pattern = r'\b' + re.escape(alias) + r'\b'
        # Only replace if it's not already part of the official name
        if not re.search(r'\b' + re.escape(alias) + r'\b', official):
            normalized = re.sub(pattern, official, normalized)
        
    # Remove excessive spaces
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized
