# 🚓 POLITI UPDATE til Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/RMolbaek/ha-politi-update/actions/workflows/validate.yml/badge.svg)](https://github.com/RMolbaek/ha-politi-update/actions/workflows/validate.yml)
![version](https://img.shields.io/badge/version-0.2.0-blue.svg)

Uofficiel Home Assistant-integration, der henter **POLITI UPDATE** fra dansk
politi ind i Home Assistant. Ved opsætning **krydser du af, hvilke politikredse**
du vil følge — og kan valgfrit **filtrere på kategori** (trafik, efterlysninger
osv.). Der oprettes både en **sensor** og en **event-entitet** pr. valgt kreds.

Feedsene er de officielle offentlige RSS-feeds, som politiet distribuerer via
Ritzau (`via.ritzau.dk`).

---

## ⚡ Hurtig installation

### 1. Tilføj repoet til HACS

[![Åbn i HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=RMolbaek&repository=ha-politi-update&category=integration)

Eller manuelt: **HACS → ⋮ → Custom repositories** → indsæt
`https://github.com/RMolbaek/ha-politi-update`, kategori **Integration** →
installér **POLITI UPDATE** → **genstart Home Assistant**.

### 2. Tilføj integrationen

[![Åbn din Home Assistant og start opsætning af en ny integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=politi_update)

Eller manuelt: **Indstillinger → Enheder & tjenester → Tilføj integration →
POLITI UPDATE**.

> **Bemærk:** "Åbn i Home Assistant"-knapperne bruger [my.home-assistant.io](https://my.home-assistant.io)
> og peger på RMolbaek/ha-politi-update.

### Manuel installation (uden HACS)
Kopiér mappen `custom_components/politi_update` ind i din HA-konfigurations
`custom_components/`-mappe, og genstart Home Assistant.

---

## ⚙️ Opsætning

I opsætnings-dialogen vælger du:

| Felt | Beskrivelse |
| --- | --- |
| **Politikredse** | Kryds én eller flere af de 15 feeds af (12 kredse + Rigspolitiet + NSK + "Alle politikredse"). |
| **Kategorier** *(valgfrit)* | Begræns til fx kun `Trafik` eller `Efterlysning`. Tomt = alle meldinger. |
| **Opdateringsinterval** | Minutter mellem hentninger (standard 5). Sæt det ikke for lavt. |

Alt kan ændres senere under **Konfigurer** på integrationen — uden at fjerne og
tilføje den igen.

---

## 🧩 Entiteter

For hver valgt kreds oprettes:

### `sensor.<kreds>` — fx `sensor.oestjyllands_politi`
- **Tilstand:** antal aktuelle (evt. kategori-filtrerede) meldinger i feedet.
- **Attributter:**
  - `latest_title`, `latest_link`, `latest_published`, `latest_categories`
  - `filter_categories` — hvilke kategorier sensoren er begrænset til
  - `entries` — liste med alle meldinger, hver med
    `title`, `link`, `summary`, `published`, `published_iso`, `id`, `categories`

### `event.<kreds>` — fx `event.oestjyllands_politi`
Udløses hver gang der kommer en **ny melding** (event-type `ny_melding`).
Bedst til automatiserings-triggere. Event-data: `district`, `title`, `link`,
`published`, `categories`.

---

## 🏷️ Kategorier

Politiets feed indeholder **ikke** et kategori-felt, så kategorien udledes
heuristisk ud fra nøgleord i titlen:

| Kategori | Matcher fx |
| --- | --- |
| **Trafik** | uheld, færdsel, motorvej, lyskryds, spærret, glat … |
| **Efterlysning** | efterlys, savnet, forsvundet, "hjælp politiet" … |
| **Kriminalitet** | skud, overfald, vold, røveri, indbrud, kniv, drab … |
| **Øvrige** | alt, der ikke matcher ovenstående |

En melding kan have flere kategorier. Det er "godt nok" til filtrering, men ikke
en officiel klassificering — juster nøgleordene i `const.py`, hvis du vil.

---

## 🔔 Eksempler

### 1. Push-besked til mobilen ved ny melding (event-entitet)

```yaml
automation:
  - alias: Politi Update – ny melding
    trigger:
      - platform: state
        entity_id: event.oestjyllands_politi
    condition:
      - condition: template
        value_template: "{{ trigger.to_state.state not in ['unknown', 'unavailable'] }}"
    action:
      - service: notify.mobile_app_DIN_TELEFON
        data:
          title: "🚨 {{ trigger.to_state.attributes.district }}"
          message: "{{ trigger.to_state.attributes.title }}"
          data:
            url: "{{ trigger.to_state.attributes.link }}"
```

### 2. Kun efterlysninger → besked + oplæsning

```yaml
automation:
  - alias: Politi Update – efterlysninger
    trigger:
      - platform: state
        entity_id: event.oestjyllands_politi
    condition:
      - condition: template
        value_template: >
          {{ 'Efterlysning' in (trigger.to_state.attributes.categories | default([])) }}
    action:
      - service: notify.mobile_app_DIN_TELEFON
        data:
          title: "🔎 Efterlysning"
          message: "{{ trigger.to_state.attributes.title }}"
      - service: tts.google_translate_say
        data:
          entity_id: media_player.stue
          message: "Ny efterlysning fra politiet: {{ trigger.to_state.attributes.title }}"
```

### 3. Kun trafik → blink med en lampe

```yaml
automation:
  - alias: Politi Update – trafikvarsel
    trigger:
      - platform: state
        entity_id: event.oestjyllands_politi
    condition:
      - condition: template
        value_template: >
          {{ 'Trafik' in (trigger.to_state.attributes.categories | default([])) }}
    action:
      - service: light.turn_on
        target:
          entity_id: light.entre
        data:
          flash: short
          color_name: blue
```

### 4. Alternativ trigger uden event-entitet (sensor-attribut)

```yaml
automation:
  - alias: Politi Update – via sensor
    trigger:
      - platform: state
        entity_id: sensor.oestjyllands_politi
        attribute: latest_link
    condition:
      - condition: template
        value_template: "{{ trigger.to_state.attributes.latest_link | default('') != '' }}"
    action:
      - service: notify.persistent_notification
        data:
          title: "{{ trigger.to_state.attributes.district }}"
          message: >
            {{ trigger.to_state.attributes.latest_title }}
            {{ trigger.to_state.attributes.latest_link }}
```

---

## 📊 Dashboard-kort

### Simpelt markdown-kort med de seneste 5 meldinger

```yaml
type: markdown
content: |
  ## 🚓 Østjyllands Politi
  {% for e in state_attr('sensor.oestjyllands_politi', 'entries')[:5] %}
  **{{ e.title }}**
  _{{ e.published }} · {{ e.categories | join(', ') }}_
  [Læs mere]({{ e.link }})
  ---
  {% endfor %}
```

### Kort der kun viser efterlysninger

```yaml
type: markdown
content: |
  ## 🔎 Efterlysninger
  {% set items = state_attr('sensor.oestjyllands_politi', 'entries')
     | selectattr('categories', 'contains', 'Efterlysning') | list %}
  {% if items | length == 0 %}
  _Ingen aktuelle efterlysninger._
  {% else %}
  {% for e in items[:5] %}
  - [{{ e.title }}]({{ e.link }}) — _{{ e.published }}_
  {% endfor %}
  {% endif %}
```

---

## 🎨 Ikon

Entiteterne bruger MDI-ikonet **`mdi:police-badge`** som standard.

**Blåt brand-logo** (det der vises på integrationen i *Enheder & tjenester* og i
HACS) ligger som PNG/SVG i mappen [`brands/`](brands). Home Assistant henter dog
brand-logoer fra det officielle [`home-assistant/brands`](https://github.com/home-assistant/brands)-repo,
så for at få det vist skal filerne indsendes som en PR dertil:

```
custom_integrations/politi_update/icon.png     (256×256)
custom_integrations/politi_update/icon@2x.png  (512×512)
```

Indtil da vises et standard-puslespilsikon — det påvirker ikke funktionaliteten.

**Blåt ikon på dashboardet:** entitets-ikonets farve styres af frontend/tema, ikke
af integrationen. Vil du have det politiblåt på et kort, kan du bruge
[card-mod](https://github.com/thomasloven/lovelace-card-mod):

```yaml
type: entities
entities:
  - entity: sensor.oestjyllands_politi
    card_mod:
      style: |
        :host { --paper-item-icon-color: #0B5CAB; }
```

## ❓ Fejlfinding

- **Ingen entiteter oprettet?** Tjek at du valgte mindst én kreds, og genstart HA.
- **Entitets-id passer ikke i eksemplerne?** Slå det rigtige navn op under
  **Udviklerværktøjer → Tilstande** (fx `sensor.rigspolitiet`).
- **For mange/få meldinger?** Juster kategori-filteret under **Konfigurer**.
- **Event udløser ikke ved opstart:** Det er meningen — kun *nye* meldinger efter
  opstart udløser event-entiteten.

---

## ⚠️ Ansvarsfraskrivelse

Dette er et **uofficielt** hobbyprojekt uden tilknytning til dansk politi,
Rigspolitiet eller Ritzau. Data leveres "as is" fra det offentlige POLITI
UPDATE-feed og må ikke bruges som erstatning for **112** i nødsituationer.

## 📄 Licens

[MIT](LICENSE)
