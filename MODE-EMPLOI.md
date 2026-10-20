# Anonymiseur, mode d'emploi

Ce document est en français, contrairement au reste du dépôt : il
s'adresse à la personne qui utilise le logiciel, pas à celle qui le lit.

## Installer

Télécharger `Anonymiseur.exe` depuis la dernière version publiée, à
l'adresse https://github.com/gluon/docx-anonymizer/releases, et
double-cliquer. Il n'y a rien à installer, aucun compte, aucune
connexion.

Au premier lancement, Windows affiche un avertissement : le fichier n'est
pas signé. Cliquer sur « Informations complémentaires », puis sur
« Exécuter quand même ». L'avertissement ne reviendra pas.

## Un mail, ou un extrait

1. « Coller du texte », coller le contenu, « Analyser ».
2. Lire la grille, décocher ce qui ne doit pas être masqué.
3. « Produire la version anonyme », puis « Copier ».
4. Travailler avec l'IA sur ce texte, autant d'allers-retours que
   nécessaire.
5. « J'ai la réponse de l'IA », coller la réponse, « Remettre les vrais
   noms ».

## Un document Word

1. « Ouvrir un document Word », choisir le fichier, lire la grille.
2. « Produire la version anonyme ». Un fichier suffixé `_ANON` est écrit
   à côté de l'original, qui n'est jamais modifié. Le nom du fichier est
   masqué lui aussi : `Conclusions_Lenoir.docx` devient
   `Conclusions_Lemoine_ANON.docx`, parce qu'un nom de fichier est la
   première chose que lit celui qui le reçoit.
3. Soumettre ce fichier `_ANON` à l'IA, récupérer la version corrigée.
4. « Reprendre, et remettre les vrais noms », ouvrir le fichier corrigé.
   Un fichier suffixé `_FINAL` est écrit, avec les vrais noms.

La mise en page du document n'est pas touchée : styles, en-tête, pied de
page, tableaux, révisions suivies, commentaires. Les noms cachés dans
les propriétés du fichier, l'auteur des commentaires et celui des
révisions sont masqués aussi.

## Un dossier, plusieurs pièces

Pour traiter plusieurs pièces d'une même affaire ensemble, « Un dossier,
plusieurs pièces » sur l'écran d'accueil, puis « Ajouter un document
Word » et « Ajouter un texte collé » autant de fois que nécessaire, puis
« Analyser le dossier ».

L'intérêt est là : un même nom reçoit le même pseudonyme dans toutes les
pièces. Les conclusions et les mails parlent de la même personne, et
l'IA peut suivre un raisonnement d'une pièce à l'autre.

« Produire les pièces anonymes » demande une fois où écrire, puis affiche
la liste de ce qui a été produit, avec « Copier » ou « Ouvrir le
dossier » pour chaque pièce. Une pièce refusée n'empêche pas les autres.

« Enregistrer la table du dossier » écrit un fichier qui permet de
reprendre le dossier plus tard, pour y ajouter une pièce ou pour
restituer les vrais noms d'un document déjà envoyé. Ce fichier contient
les vrais noms : il reste sur cet ordinateur, à sa place dans le dossier
de l'affaire, et ne se transmet pas.

## Masquer soi-même ce que l'outil n'a pas vu

Depuis la grille, « Relire le texte » montre le texte avec en jaune ce
qui sera remplacé. Sélectionnez ce qui doit l'être aussi, puis Ctrl+M ou
« Masquer la sélection ».

À utiliser pour ce qu'aucune règle ne peut deviner : un surnom, un poste
qui ne désigne qu'une personne dans une petite entreprise, le numéro
d'une machine, une date qui ne parle qu'aux parties. Ce qui a la forme
d'un nom reçoit un nom, le reste reçoit un jeton entre crochets.

C'est aussi le seul écran qui répond à « qu'est-ce qui va sortir
exactement », ce qu'aucun tableau ne dit.

## Lire la grille

Une ligne par valeur trouvée, avec la raison pour laquelle elle a été
trouvée. Case cochée veut dire masquer.

- **Certain** : un numéro de sécurité sociale, un IBAN, un SIRET, une
  adresse, un téléphone, un courriel, une référence de dossier. La clé de
  contrôle a été vérifiée quand il y en a une. Déjà coché.
- **À confirmer** : un mot qui ressemble à un nom propre. Coché par
  défaut, parce qu'un nom oublié ne se voit jamais et qu'un mot masqué à
  tort se voit tout de suite.
- **Jurisprudence** : une partie à une décision citée. Décoché, parce que
  masquer le nom d'un arrêt détruit la citation.

Un nom écrit de plusieurs façons reçoit un seul pseudonyme, à la forme de
chaque graphie : `Mme LENOIR`, `Lenoir` et `Sophie Lenoir` restent la
même personne.

## Ce qu'il faut savoir avant de commencer

**Une fenêtre, un cycle.** La table qui relie les vrais noms aux
pseudonymes n'existe qu'en mémoire, et n'est écrite nulle part. Fermer la
fenêtre, ou cliquer sur « Effacer le cycle », l'efface définitivement. Le
fichier masqué reste lisible, mais plus personne ne peut y remettre les
vrais noms.

Donc : ne pas fermer la fenêtre avant d'avoir remis les vrais noms. Si le
travail avec l'IA doit durer, laisser la fenêtre ouverte.

**Le logiciel peut refuser d'écrire.** Deux cas, et ce sont des
protections, pas des pannes :

- une vraie valeur a survécu au masquage. Rien n'est écrit. Vérifier la
  grille : en général un pseudonyme contient un mot qui doit lui aussi
  être masqué, et la fenêtre le dit en clair.
- au retour, un pseudonyme a disparu du texte renvoyé. L'IA l'a reformulé,
  et il ne peut plus être restitué. Le document reviendrait à moitié vrai,
  donc rien n'est écrit. Redemander à l'IA de conserver les noms tels
  quels.

**Rien ne sort de cet ordinateur.** Aucune connexion réseau, aucun fichier
temporaire, aucun historique. Le bandeau en haut de la fenêtre le dit à
chaque instant et compte les tentatives de connexion, qui doivent rester
à zéro.

## Ce que le logiciel ne fait pas

Il ne lit pas les images ni les pièces scannées. Si un document contient
une image, la fenêtre le signale : l'image sort telle quelle, et ce qui
est écrit dessus n'est pas masqué.

Il ne connaît pas la notion de dossier : chaque document, chaque mail est
un cycle indépendant, avec ses propres pseudonymes.
