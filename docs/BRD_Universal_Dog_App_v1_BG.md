# BRD — Universal Dog Owner App

**Версия:** 1.0  
**Дата:** 13.09.2026  
**Статус:** Product baseline / ready for refinement  
**Работно име:** Universal Dog App (финалното име е TBD)

---

## 1. Executive Summary

Целта е съществуващата концепция „едно приложение за една порода“ да бъде заменена с **едно глобално приложение за всички кучета**, което се персонализира според конкретното куче — порода, смесена порода/неизвестен произход, възраст, размер, пол, държава, здравен профил и история.

Новото приложение не трябва визуално или UX-wise да изглежда като сбор от старите breed apps. То трябва да бъде нов продукт с нова информационна архитектура, нов onboarding, нов home experience и централен персонализиран lifecycle модул.

Основната продуктова идея е:

> **Приложение, което познава твоето куче и се променя заедно с него.**

Функции като здравно досие, Travel & ID, Nearby, Pack, pedigree и sharing са отделни capabilities. Основният retention engine е персонализираният lifecycle модул **Journey**.

---

## 2. Business Goals

1. Един глобален продукт вместо отделни приложения по порода.
2. Покриване на pure breed, mixed breed и unknown breed dogs.
3. Максимално повторно използване на съществуващия backend/domain модел.
4. Значително по-добър onboarding и daily engagement.
5. Увеличаване на retention чрез Journey и smart reminders.
6. Запазване на privacy-first social модела.
7. Безплатна data migration от Beagle Owner.
8. Единен subscription/entitlement модел.
9. Глобална локализация и country-aware Travel & ID.
10. Добавяне на нови породи и lifecycle content без app release.

### Success Metrics
- Onboarding completion rate
- Dog profile completion rate
- D1 / D7 / D30 retention
- Journey weekly engagement
- Health record adoption
- Nearby usage
- Pack friendship creation rate
- Walk creation / RSVP rate
- Trial → paid conversion
- Beagle Owner migration completion
- Average dogs per account
- Crash-free sessions
- Privacy/reporting incidents

---

## 3. Product Principles

### P1. Dog first
Всички ключови функции са организирани около конкретно куче, а не около owner profile.

### P2. Progressive disclosure
По време на onboarding се събират само данните, необходими за старт. Останалото се попълва постепенно.

### P3. Privacy by default
Community visibility е OFF. Няма публичен owner profile. Няма user search. Няма chat.

### P4. Contextual permissions
Location, notifications, camera и други permissions се искат, когато потребителят използва функцията, а не при първо стартиране.

### P5. One product, personalized experience
UI остава единен; породата влияе на съдържанието и лек accent color, но не създава различни приложения.

### P6. Explain before asking
Преди sensitive permission или важен избор приложението обяснява защо информацията е необходима.

### P7. No false precision
При mixed/unknown dogs Journey показва guidance с ясно обяснение върху какво е базиран.

---

## 4. Personas

- **Single-dog owner** — едно куче, здраве, reminders, nearby services, Journey.
- **Multi-dog household** — няколко кучета с общ owner context, но отделни профили.
- **Co-owner** — пълен, отменяем достъп до конкретно куче.
- **Social owner** — Pack, QR friendships, walks, park notification, live sharing.
- **Traveler** — Travel & ID, microchip, passport/travel documents.
- **Legacy Beagle Owner user** — мигрира данни и не се таксува повторно за еквивалентен активен entitlement.

---

## 5. Scope

### In Scope
- Account / authentication
- Multi-dog profiles
- Pure / mixed / unknown breed
- Country-aware experience
- Journey
- Health dossier
- Weight tracking
- Vaccinations
- Vet visits
- Medications
- Conditions / allergies
- Labs/documents
- Diet
- Female-specific lifecycle data when applicable
- Travel & ID
- Microchip
- Passport / travel document
- Nearby vets / emergency vets / dog hotels
- Pack
- QR friendship
- Friends list
- Temporary live location
- Privacy-preserving community presence
- “I’m at the park”
- Group walks + RSVP
- Pedigree
- Co-ownership
- Vet sharing
- Shows
- Reporting / blocking
- Notifications
- Subscription
- Beagle Owner migration
- Localization

### Out of Scope for v1
- Owner-to-owner chat
- Public owner profiles
- Forums
- Comments
- Likes/reactions
- Search for owners by name
- Public exact geolocation
- Open DMs
- Marketplace
- Breeder marketplace
- Veterinary diagnosis
- Medication prescribing

---

## 6. Information Architecture

Primary navigation:

1. **Today**
2. **Health**
3. **Nearby**
4. **Pack**
5. **My Dog**

Global elements:
- Dog switcher
- Notifications center
- Account / Settings
- Subscription state
- Language
- Default country
- Help / Support

### Today
- Daily personalized overview
- Journey snapshot
- Upcoming reminders
- Health alerts
- Suggested actions
- Emergency vet shortcut
- Pack activity

### Health
- Health overview
- Weight
- Vaccinations
- Vet visits
- Medications
- Conditions
- Allergies
- Labs/documents
- Diet
- Female-specific records
- Export dossier

### Nearby
- Vets
- Emergency vets
- Dog hotels
- Map/List
- Radius
- Open now
- Phone
- Directions

### Pack
- Meet a dog
- QR show/scan
- Friends
- Nearby dogs
- Walks
- I’m at the park
- Live location
- Social notification settings

### My Dog
- Dog profile
- Travel & ID
- Pedigree
- Shows
- Access & Sharing
- Privacy
- Dog-specific settings

---

## 7. Onboarding Requirements

### FR-ONB-001 Splash
Splash screen shows multiple dog breeds and product branding.

### FR-ONB-002 Language
User selects UI language. Device locale may be proposed, but must be changeable.

### FR-ONB-003 Country
User selects current country of residence.

Suggested copy:
> We use your country to show relevant travel documents, local guidance and nearby services. You can change it later.

**Important:** Country of residence and passport issuing country are separate data fields.

The app must not force passport replacement solely because residence country changes.

### FR-ONB-004 Dog name
Required.

### FR-ONB-005 Breed
Options:
- Search breed
- Popular breeds
- All breeds
- Mixed breed
- I don't know

### FR-ONB-006 Mixed breed
If known:
- multiple breed components
- optional percentage

If unknown:
- expected adult size
- current weight
- age
- sex
- coat length (optional)
- neutered/spayed state (optional)

### FR-ONB-007 Age
Allow exact DOB, approximate DOB, age-only, unknown.

### FR-ONB-008 Sex
Male / Female / Unknown.

### FR-ONB-009 Optional personalization
Offer photo, weight, health information, microchip, known conditions, neuter state.

Must have:
**I'll do this later**

### FR-ONB-010 Ready state
Show:
> Max is ready.

Then offer a short product tour.

### FR-ONB-011 Product tour
Maximum 5 screens:
1. Today + Journey
2. Health + Travel & ID
3. Nearby
4. Pack
5. Pedigree / Sharing

Tour must be skippable.

---

## 8. Multi-Dog Model

### FR-DOG-001
One User can own or co-own multiple Dogs.

### FR-DOG-002
Language is account-level by default.

### FR-DOG-003
Country is modeled as:
- account default country
- dog current residence country

### FR-DOG-004
When adding another dog:
- owner data inherited
- language inherited
- country proposed from account default
- onboarding starts from dog name

### FR-DOG-005 Country change
If multiple dogs exist:
> Apply this country change to:
> - This dog only
> - All my dogs

### FR-DOG-006
Passport issuer country never changes automatically when residence changes.

---

## 9. Breed Model

### BREED_TYPE
- PURE
- MIXED_KNOWN
- MIXED_UNKNOWN
- UNKNOWN

### Breed profile content
Each breed may define:
- expected size
- expected weight curves
- growth milestones
- life-stage boundaries
- temperament tendencies
- exercise guidance
- nutrition guidance
- grooming guidance
- breed-associated health risks
- training notes
- fun facts

Breed content must be server-driven and versioned. No lifecycle/breed knowledge should be hardcoded in Flutter UI.

---

## 10. Journey

### Purpose
Journey answers:
> What is happening with my dog now, what can I expect next, and what should I pay attention to?

### Inputs
- breed / breed mix
- age
- size
- sex
- neuter state
- weight
- health data
- country
- recorded vaccinations
- previous Journey interactions

### Content categories
- Growth
- Nutrition
- Feeding frequency
- Weight
- Behaviour
- Temperament
- Training
- Activity
- Preventive care
- Grooming
- Development milestones
- Senior changes
- Fun facts

### Journey stages
- Newborn
- Puppy
- Juvenile
- Adolescent
- Young adult
- Adult
- Mature
- Senior

Exact boundaries may vary by breed/size.

### Mixed/unknown behavior
Pure breed: breed-specific model.

Mixed known: weighted breed guidance + size normalization.

Mixed unknown: size/age/weight based model.

UI must disclose basis:
> Guidance for Max is based on his age, size and current profile rather than a specific breed.

### Health safety
Journey must never diagnose or prescribe.

Avoid:
- “Give supplement X”
- “Your dog has condition Y”

Use:
- “Ask your veterinarian whether…”
- “At this stage, your veterinarian may recommend reviewing…”

Country-specific vaccination guidance must be configurable and medically reviewed.

---

## 11. Health Module

### FR-HLT-001 Health overview
Shows next relevant action, weight trend, vaccine status, active medication, known allergy, last vet visit.

### FR-HLT-002 Weight
- add measurement
- history
- chart
- expected breed/size range when applicable
- notes

### FR-HLT-003 Vaccinations
- vaccine
- date
- valid until / next due
- vet
- document/photo
- reminder

### FR-HLT-004 Vet visits
- reason
- date
- vet
- notes
- owner-entered diagnosis record
- attachments
- follow-up

### FR-HLT-005 Medication
- medicine
- dose as entered by user/vet record
- schedule
- start/end
- reminders
- notes

### FR-HLT-006 Conditions
Chronic / historic conditions.

### FR-HLT-007 Allergies
Type, reaction, notes.

### FR-HLT-008 Labs/Documents
Files, result metadata, date, vet.

### FR-HLT-009 Diet
Current food, feeding pattern, changes, notes.

### FR-HLT-010 Female-specific
Heat cycle and related record types only when relevant.

### FR-HLT-011 Export
Owner can export/share selected dossier data.

---

## 12. Travel & ID

### FR-TRV-001
Global module name: **Travel & ID**

### FR-TRV-002 Microchip
- number
- implant date
- location
- issuer/registry optional

### FR-TRV-003 Travel documents
Document model supports:
- EU Pet Passport
- national/other passport
- animal health certificate
- other document

Fields:
- document number
- issuing country
- issuing authority/vet
- issue date
- expiry if applicable
- attachments

### FR-TRV-004 Country awareness
Residence country influences guidance, units, nearby services and travel checklist. It does not overwrite passport issuer.

### FR-TRV-005 Travel readiness
Optional checklist based on origin/destination and stored data. Requirements must be treated as changeable and verified against authoritative sources.

---

## 13. Nearby

### FR-NBY-001 Categories
- Vets
- Emergency vets
- Dog hotels

### FR-NBY-002
Map/list toggle.

### FR-NBY-003
Radius selector in km/mi.

### FR-NBY-004 Place card
- name
- distance
- open/closed when available
- rating when available
- phone
- 24/7 indicator
- directions

### FR-NBY-005
Location permission requested only when Nearby is opened or location is required.

### FR-NBY-006
Today page provides prominent “Emergency vet” action.

---

## 14. Pack — Social Layer

### Core principle
Social relationship is **Dog ↔ Dog**, not Owner ↔ Owner. Owners do not get public profiles.

### FR-PACK-001 Meet a dog
- Show my QR
- Scan QR

QR token validity: 10 minutes.

Successful scan creates dog friendship.

### FR-PACK-002 Friends
Per-dog friends list.

Actions:
- view allowed dog profile
- share live location
- I’m at the park
- remove friend
- block/report when applicable

### FR-PACK-003 Social gating
Most social functionality requires existing dog friendship.

### FR-PACK-004 Live Location
Exact live location can be shared with dog friends for 5, 10, 15, 30 or 60 minutes.

Requirements:
- explicit opt-in
- visible countdown
- Stop sharing
- automatic expiry
- backend TTL deletion

### FR-PACK-005 Community Presence
Default: OFF.

Owner may enable:
> Show my dog in the community

Precision:
- City (~1 km cell)
- Country (~100 km cell)

Exact/raw location must be quantized client-side before server transmission for community presence.

### FR-PACK-006 Nearby Dogs filter
Applies only to discovery:
- My breed
- All

### FR-PACK-007 I’m at the park
One-time push to owners of the dog’s friends. Optional text. No event creation required.

### FR-PACK-008 Walks
Create:
- location
- date/time
- message
- intended audience

Discovery uses configured radius/current behavior baseline and filter My breed / All.

RSVP is with a specific dog.

### FR-PACK-009 Pack notifications
Controls:
- group walks
- friend at park
- dog news

### FR-PACK-010 No chat
No owner-to-owner direct messaging in v1.

---

## 15. Safety / Moderation / Privacy

### FR-SAFE-001 Report
User can report content/user/dog-related interaction.

### FR-SAFE-002 Block
Two-way block:
- removed from friends
- hidden from maps
- hidden from walks
- no notifications
- visibility rules enforced globally

### FR-SAFE-003 Shared visibility middleware
All list retrieval, entity-by-id, notifications, files and map data must pass the same visibility policy.

### FR-SAFE-004 Blocked list
Available under Privacy & Safety.

### FR-SAFE-005 Owner privacy
No public owner profile, owner search or follower model.

---

## 16. Co-Ownership and Vet Sharing

### FR-SHR-001
Located under **My Dog → Access & Sharing**.

### FR-SHR-002 Co-owner
Invite via QR or secure link.

Co-owner access:
- full dog access
- revocable
- audit history

### FR-SHR-003 Veterinary share
Read-only secure link/QR to selected dossier data.

Recommended:
- data scope selection
- expiry
- revoke anytime
- access log

---

## 17. Pedigree

### FR-PED-001
Parent/child relationships between dogs.

### FR-PED-002
Allow:
- Link existing dog
- Add placeholder relative

### FR-PED-003 Visibility
Pedigree relation visible when:
- owner enabled public pedigree, OR
- dogs are friends

### FR-PED-004
Interactive tree/graph.

### FR-PED-005
Show app-linked relatives distinctly.

Example:
> 3 of 14 known relatives are on the app.

---

## 18. Shows

Store dog show results:
- event
- date
- location
- class
- result
- judge
- notes
- certificate/photo

Private by default.

---

## 19. Notifications

Types:
- health reminder
- vaccination
- medication
- Journey milestone
- smart Journey suggestion
- friend at park
- group walk
- RSVP
- co-owner invitation
- vet share expiry
- migration
- subscription/trial state

Use contextual permission request.

---

## 20. Subscription

Working commercial assumption:
- 30-day free trial
- €0.99/month baseline
- localized store prices

Requirements:
- server-side entitlement state
- Apple validation
- Google validation
- Restore Purchases
- subscription state UI
- graceful expiration
- no duplicate entitlement

---

## 21. Beagle Owner Migration

### Business requirement
Migration of existing user data into the new app is free.

### Recommended entitlement policy
An active legacy Beagle Owner subscription grants equivalent premium access in the new app while that entitlement remains active.

Do not charge the same user twice for equivalent service.

If the business wants “lifetime premium after migration”, this is a separate commercial decision and is **not assumed** by this BRD.

### Architecture
Use same backend identity/account where possible.

Normalized entitlement model:

```text
ENTITLEMENT
user_id
source_store
source_app
product_id
transaction_or_purchase_token
status = ACTIVE | GRACE | EXPIRED | REVOKED
valid_until
normalized_type = PREMIUM
```

### Data migration
Legacy data:
- dog profile
- health records
- passport/travel
- weight
- pedigree
- social relationships where model-compatible
- files
- settings

New app:
- import event with idempotency key
- migration status
- conflict reconciliation

### UX
Legacy app:
> Beagle Owner is growing.  
> Move Max to the new app.

New app:
> We found Max.

Preview record counts, then **Import Max**.

Completion:
> Welcome home, Max.

### Store architecture
Apple supports offering equivalent subscription access across multiple apps using a unified account database and server-side validation. Google purchase tokens should be verified server-side and mapped to normalized user entitlements.

---

## 22. High-Level Data Model

```text
USER
 ├── ACCOUNT_PREFERENCES
 ├── ENTITLEMENTS
 ├── NOTIFICATION_PREFERENCES
 └── DOGS
      ├── DOG_PROFILE
      ├── BREED_COMPONENTS
      ├── RESIDENCE
      ├── HEALTH_RECORDS
      ├── TRAVEL_DOCUMENTS
      ├── MICROCHIP
      ├── PEDIGREE_EDGES
      ├── SHOW_RESULTS
      ├── FRIENDSHIPS
      ├── COMMUNITY_VISIBILITY
      ├── LIVE_LOCATION_SESSIONS
      ├── WALK_RSVPS
      └── ACCESS_GRANTS
```

Content model:

```text
BREED_PROFILE
LIFE_STAGE_RULE
JOURNEY_CONTENT
COUNTRY_RULESET
LOCALIZATION
```

---

## 23. Non-Functional Requirements

### Security
- TLS
- secure device storage
- server-side purchase validation
- short-lived sharing tokens
- signed URLs
- server-side access control
- audit logs for sensitive sharing

### Privacy
- data minimization
- community presence OFF by default
- client-side coarse location quantization for community mode
- precise live location ephemeral
- account/dog deletion
- export
- consent logging where required

### Performance
- cached home content with fast first meaningful render
- skeleton loading
- offline cache for core dog profile/health summary
- retry-safe writes

### Accessibility
- dynamic text
- screen-reader labels
- accessible contrast
- no color-only state
- minimum touch targets

### Internationalization
- server content localized
- RTL readiness
- metric/imperial
- locale dates
- localized currency

---

## 24. Analytics Events

Core funnel:
- onboarding_started
- language_selected
- country_selected
- breed_selected
- onboarding_completed
- optional_profile_completed

Engagement:
- journey_opened
- journey_card_opened
- weight_added
- vaccination_added
- vet_found
- hotel_found
- emergency_vet_opened
- qr_generated
- qr_scanned
- friendship_created
- live_location_started
- park_ping_sent
- walk_created
- walk_rsvp
- pedigree_linked
- vet_share_created

Revenue:
- trial_started
- paywall_viewed
- subscription_started
- subscription_restored
- subscription_expired

Migration:
- legacy_migration_started
- legacy_data_detected
- legacy_migration_completed
- legacy_migration_failed

---

## 25. Content Governance

Breed and Journey content must have:
- version
- source
- reviewer state where medically relevant
- locale
- effective date
- archived state

Country travel rules must support:
- effective_from
- effective_to
- source reference
- last_reviewed_at

---

## 26. Key Risks

1. Journey content can accidentally sound like medical diagnosis.
2. Too-long onboarding may reduce conversion.
3. Mixed breed personalization can imply false precision.
4. Location features must preserve existing privacy guarantees.
5. Multi-dog permissions can become confusing.
6. Legacy entitlement migration can cause double charging if not centralized.
7. Travel rules change and require content governance.
8. Scope creep toward a full social network must be resisted.

---

## 27. Recommended Release Scope

### MVP
- onboarding
- multi-dog
- Today
- Journey v1
- Health
- Travel & ID
- Nearby
- Pack existing functionality
- Pedigree
- Co-owner
- Vet sharing
- subscription
- Beagle migration
- privacy/moderation

### Post-MVP
- advanced mixed-breed inference
- richer Journey personalization
- friends-of-friends discovery
- more travel planning
- advanced health insights
- provider partnerships

---

## 28. Product Decisions Locked by This BRD

- One app for all breeds.
- No owner social network.
- Friendship is dog-to-dog.
- No chat in v1.
- Country of residence ≠ passport issuing country.
- Community presence is opt-in and coarse.
- Live exact location is temporary and friend-gated.
- Co-owner and vet sharing are not Pack features.
- Pedigree lives under My Dog.
- Journey is the core retention feature.
- Breed rules are server-driven.
- Mixed/unknown dogs are first-class citizens.
- Legacy purchases are normalized through a backend entitlement service.

---

## 29. Open Decisions

1. Final product name.
2. Final premium/free feature boundary.
3. Exact legacy commercial policy after old subscription expiry.
4. Country rollout plan.
5. Final Journey content review process.
6. Provider for nearby places.
7. Whether placeholder pedigree relatives may later be claimed by another user.

---

## Reference Notes

- EU pet passport: European Union / Your Europe states that the passport is valid for life as long as relevant health information remains valid.  
  https://europa.eu/youreurope/citizens/travel/carry/pets-and-other-animals/index_en.htm

- Apple StoreKit — Offering a Subscription Across Multiple Apps:  
  https://developer.apple.com/documentation/storekit/offering-a-subscription-across-multiple-apps

- Google Play Billing backend / entitlement verification:  
  https://developer.android.com/google/play/billing/  
  https://developer.android.com/google/play/billing/security
