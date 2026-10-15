#!/bin/sh
# Uruchamia zbieranie danych na GitHubie (workflow_dispatch). Wywoływany z crona co 5 minut, np. na lh.pl:
#   */5 * * * *  sh $HOME/pociagi/trigger.sh
# Samo zbieranie i publikacja dzieją się w GitHub Actions; ten skrypt tylko "naciska Run workflow".
#
# Token: fine-grained personal access token ograniczony do repozytorium pociagi,
# uprawnienie Actions: Read and write. Zapisany w $HOME/pociagi/.github_token (poza public_html!), chmod 600.
# Wynik ostatniego wywołania: $HOME/pociagi/trigger.log (204 = OK).

DIR="$HOME/pociagi"
REPO="mat-szymanski/pociagi"
TOKEN=$(cat "$DIR/.github_token" 2>/dev/null) || { echo "$(date '+%F %T') brak tokenu" >> "$DIR/trigger.log"; exit 1; }

code=$(curl -s -o /dev/null -w "%{http_code}" -m 30 -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "https://api.github.com/repos/$REPO/actions/workflows/collect.yml/dispatches" \
  -d '{"ref":"main"}')

# log tylko z ostatnich ~200 wywołań, żeby plik nie rósł
echo "$(date '+%F %T') HTTP $code" >> "$DIR/trigger.log"
tail -n 200 "$DIR/trigger.log" > "$DIR/trigger.log.tmp" && mv "$DIR/trigger.log.tmp" "$DIR/trigger.log"
[ "$code" = "204" ]
