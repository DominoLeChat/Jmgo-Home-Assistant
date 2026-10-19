# Jmgo Projector Integration

Integration Home Assistant pour projecteurs JMGO (mode LAN TCP)

Installation (HACS manual):
1. Dans HACS, choisissez "Intégrations" -> "..." -> "Ajouter un dépôt manuel".
2. Collez l'URL du dépôt et installez.
3. Redémarrez Home Assistant.
4. Configurez l'intégration via Configuration -> Intégrations -> Ajouter JMGO (host, port, name).

Limitations et notes
- Cette intégration utilise le contrôle LAN TCP (port par défaut 9005). Aucune dépendance ADB.
- Le media_player expose le volume normalisé (0.0–1.0) et le contrôle de volume via les commandes fournies par le protocole.
- Le mode POWER est manipulé prudemment : la commande POWER n'est envoyée que si l'état power_state est explicitement rapporté par l'appareil. Si l'état est inconnu, l'action POWER est refusée pour éviter d'éteindre ou de mettre en veille prolongée par erreur.
- Le composant partage le client réseau entre remote et media_player pour éviter des connexions concurrentes.

Tests
- Des tests unitaires sont fournis (tests/test_media_player.py) et peuvent être exécutés avec pytest.

HACS
- Un fichier hacs.json est inclus pour compatibilité HACS. Assurez-vous que le dépôt est public pour l'ajouter dans HACS.

Contributions
- Merci de fournir des trames réseau (exemples de réponse TCP) si vous voulez que je parsèe d'autres champs (source, application, etc.).
