# UX/UI Concept & Complete Screen Specification

**Project:** Universal Dog App  
**Version:** 1.0  
**Language of specification:** Bulgarian  
**UI canonical copy:** English-first, localized at runtime

---

## 1. Design Concept — “Living Companion”

Новото приложение трябва визуално да се разграничава напълно от breed-app серията.

Не използваме стария beige breed-poster aesthetic, breed logo като основен navigation element, декоративни лапи/листа на всеки екран или module-grid като Home.

Новата посока е:

> **photo-led, calm, premium, contextual, personal**

Кучето е визуалният герой. Интерфейсът се държи като персонален companion, а не като database.

---

## 2. Visual System

### Color tokens
- Background: `#F7F7F4`
- Surface: `#FFFFFF`
- Ink: `#202421`
- Muted Ink: `#6C736F`
- Primary: `#2D6A63`
- Primary Soft: `#DCEBE7`
- Journey: `#D9A15B`
- Health: `#A85E67`
- Nearby: `#517E6E`
- Pack: `#6E64A6`
- Warning: `#C27A36`
- Danger: `#B84B4B`

Breed accent is optional, subtle and never used for status semantics.

### Typography
Preferred: Inter / system fallback.

- Display: 32 / 38 semibold
- H1: 28 / 34 semibold
- H2: 22 / 28 semibold
- H3: 18 / 24 semibold
- Body: 16 / 24
- Small: 14 / 20
- Caption: 12 / 16

### Shape language
- cards: 20–24 px radius
- sheets: 28 px top radius
- chips: fully rounded
- buttons: 14–16 px radius
- 8 pt spacing grid
- large whitespace
- minimal borders

### Photography
Dog photo is large, natural and personal. No stock-photo collage in the core UI.

### Motion
- dog switch: 220–280 ms crossfade
- card expand: ~250 ms
- Journey transition: horizontal spring
- success: subtle haptic + small scale

---

## 3. Global App Shell

### Header
Left: active dog avatar/name + dropdown.  
Right: notifications + account/settings.

### Bottom navigation
1. Today
2. Health
3. Nearby
4. Pack
5. My Dog

Active dog context stays visible on dog-specific flows.

---

## 4. Screen Map

```text
APP
├── Splash
├── Onboarding
│   ├── Language
│   ├── Country
│   ├── Dog Name
│   ├── Breed
│   ├── Mixed Breed
│   ├── Age
│   ├── Sex
│   ├── Optional Profile
│   ├── Photo
│   ├── Ready
│   └── Product Tour
├── Today
│   ├── Today Home
│   ├── Journey
│   ├── Journey Card
│   ├── Reminder Detail
│   └── Notifications Center
├── Health
│   ├── Health Home
│   ├── Weight / Add Weight
│   ├── Vaccinations / Detail/Add
│   ├── Vet Visits / Detail/Add
│   ├── Medications / Detail/Add
│   ├── Conditions
│   ├── Allergies
│   ├── Labs & Documents
│   ├── Diet
│   ├── Female Health
│   └── Export Dossier
├── Nearby
│   ├── Nearby Home
│   ├── Map
│   ├── List
│   ├── Place Detail
│   ├── Emergency Vet
│   └── Location Permission
├── Pack
│   ├── Pack Home
│   ├── Meet a Dog
│   ├── Show QR
│   ├── Scan QR
│   ├── Friendship Success
│   ├── Friends
│   ├── Friend Dog
│   ├── Live Location
│   ├── Community Nearby
│   ├── Community Visibility
│   ├── I'm at the Park
│   ├── Walks
│   ├── Create Walk
│   ├── Walk Detail
│   ├── RSVP
│   └── Pack Notifications
├── My Dog
│   ├── Dog Profile
│   ├── Edit Dog
│   ├── Travel & ID
│   ├── Microchip
│   ├── Travel Documents
│   ├── Travel Document Detail
│   ├── Travel Readiness
│   ├── Pedigree
│   ├── Add/Link Relative
│   ├── Shows
│   ├── Show Result
│   ├── Access & Sharing
│   ├── Co-owners
│   ├── Invite Co-owner
│   ├── Vet Share
│   ├── Vet Share Scope
│   ├── Privacy
│   └── Dog Settings
├── Multi-Dog
│   ├── Dog Switcher
│   ├── Add Dog
│   └── Country Change Scope
├── Account
│   ├── Account
│   ├── Language
│   ├── Default Country
│   ├── Units
│   ├── Privacy & Safety
│   ├── Blocked Users
│   ├── Subscription
│   ├── Restore Purchases
│   ├── Help
│   └── Delete Account
├── Migration
│   ├── Legacy Offer
│   ├── Migration Sign-in
│   ├── Found Dog
│   ├── Import Preview
│   ├── Import Progress
│   └── Import Success
└── Paywall
    ├── Trial Offer
    ├── Subscription State
    └── Expired State
```

---

# 5. Onboarding Screens

## SCR-ONB-001 Splash
Full-screen off-white background. Central product mark with 6–8 dogs of different sizes/types arranged around it. Include at least one mixed-breed-looking dog. Bottom: product name + optional short tagline. No breed-specific branding.

## SCR-ONB-002 Language
Title: **Choose your language**  
Search field + device-locale suggestion + language list.  
CTA: **Continue**

## SCR-ONB-003 Country
Title: **Where do you and your dog live?**  
Body: **We use your country to show relevant travel documents, local guidance and nearby services. You can change it later.**  
Country picker + **Why do we ask this?**  
CTA: **Continue**

## SCR-ONB-004 Dog Name
Title: **What's your dog's name?**  
Large input. Optional photo placeholder.  
CTA: **Continue**

## SCR-ONB-005 Breed
Title: **What kind of dog is Max?**  
Search + Popular + All breeds.  
Bottom cards: **Mixed breed**, **I don't know**.

## SCR-ONB-006 Mixed Breed
Known mix: add breed components + optional percentage.  
Unknown: size chips Small / Medium / Large / Giant / Not sure.

## SCR-ONB-007 Age
Options: exact date, approximate date, age only, unknown.

## SCR-ONB-008 Sex
Cards: Male / Female / Not sure.  
Optional neuter/spay with **I'll add this later**.

## SCR-ONB-009 Optional Profile
Title: **Want to make Max's experience even better?**  
Cards: weight, health, microchip, photo.  
Primary: **Complete profile**  
Secondary: **I'll do this later**

## SCR-ONB-010 Ready
Dog photo/avatar.  
Title: **Max is ready.**  
Sub: **We'll personalize the app as you add more about him.**  
Primary: **Show me around**  
Secondary: **Go to Today**

## SCR-ONB-011 to 015 Product Tour
1. **Everything important, right now.** — Today/Journey
2. **A health record that stays with Max.**
3. **Find help around you.** — vets, emergency, hotels
4. **Your dog's real-life social circle.** — Pack/QR/privacy
5. **Build Max's family tree.** — pedigree

Tour is skippable.

---

# 6. Today

## SCR-TOD-001 Today Home
Top: `[photo] Max · Beagle · 8 months ▼` + notification icon.  
Hero: large photo + stage label + **This week with Max** Journey insight.  
Priority stack: max 3 cards.  
Quick actions: Add weight / Emergency vet / Share dossier / I'm at the park.  
Pack preview only when relevant.  
Today must never look empty.

## SCR-TOD-002 Journey
Header: **Max's Journey**  
Visual stage rail: `Puppy ━━━●━━ Adolescent ━━━ Adult ━━━ Senior`  
Cards: Growth / Food / Behaviour / Training / Activity / Health / Grooming / Fun fact.

## SCR-TOD-003 Journey Detail
Sections: What you may notice / Why it happens / What you can do / When to ask your vet.  
Actions: Save / Remind me later.

## SCR-TOD-004 Reminder Detail
Title, date, related entity.  
Actions: Done / Snooze / Edit / Delete.

## SCR-TOD-005 Notifications Center
Grouped by Today / Earlier / Social / Health. Every item deep-links to a real domain screen.

---

# 7. Health

## SCR-HLT-001 Health Home
Hero **Max's Health**. Status strip: current weight / next vaccine / active meds.  
Cards: Weight, Vaccinations, Vet visits, Medications, Conditions & allergies, Labs & documents, Diet, Female health when relevant.  
FAB: **+ Add health record**

## SCR-HLT-002 Weight
Current weight + trend chart + expected range when reliable. Tabs Trend / History. CTA Add weight.

## SCR-HLT-003 Add Weight
Weight, date/time, note. Save.

## SCR-HLT-004 Vaccinations
Tabs Upcoming / Valid / Past. Cards with vaccine, date, due date. CTA Add vaccination.

## SCR-HLT-005 Vaccination Form
Vaccine, administered date, due/valid date, vet, batch optional, attachment, reminder.

## SCR-HLT-006 Vet Visits
Timeline list. CTA Add visit.

## SCR-HLT-007 Vet Visit Detail
Reason, notes, recorded diagnosis, files, medication, follow-up.

## SCR-HLT-008 Medications
Active first. Card: name, schedule, end, next dose.

## SCR-HLT-009 Medication Detail/Add
Name, dose text, frequency, start/end, reminders, vet, note.

## SCR-HLT-010 Conditions & Allergies
Separate sections. Status text plus accessible visual markers.

## SCR-HLT-011 Labs & Documents
File cards with type/date/vet/preview + filters.

## SCR-HLT-012 Diet
Current diet hero + food, type, daily amount, meals/day, started, notes, history.

## SCR-HLT-013 Female Health
Conditional only. Heat cycles and relevant records/reminders.

## SCR-HLT-014 Export Dossier
Selectable sections: identity, vaccines, visits, medication, allergies, labs, weight. Output PDF/export or secure vet link.

---

# 8. Nearby

## SCR-NBY-001 Nearby Home
Top search/location. Segment: Vets / Emergency / Hotels. Map/List toggle. Filters distance / open now / 24/7.

## SCR-NBY-002 Map
Pins + bottom result carousel. This is service map, separate from community dog map.

## SCR-NBY-003 List
Cards: name, distance, open state, rating, 24/7, phone. Actions Call / Directions.

## SCR-NBY-004 Place Detail
Name/category, hours, distance, phone, address, rating. Primary Directions, secondary Call.

## SCR-NBY-005 Emergency Vet
Minimal high-priority UI. Nearest open options first. Large Call / Directions actions.

## SCR-NBY-006 Location Permission
Pre-permission: **Find services around Max**. Explain value. Continue / Not now.

---

# 9. Pack

## SCR-PACK-001 Pack Home
Header **Max's Pack**. Stats `12 friends · 2 nearby · 1 walk`. Four large actions: Meet a dog / Friends / Nearby / Walks. Quick action **I'm at the park**. Active live sharing appears as persistent countdown card.

## SCR-PACK-002 Meet a Dog
Two cards: **Show my QR** / **Scan a QR**. Privacy note: **Owners stay private.**

## SCR-PACK-003 Show QR
Large QR + dog avatar/name + `Valid for 09:42`. No owner identity.

## SCR-PACK-004 Scan QR
Camera target + fallback Enter code. Permission only here.

## SCR-PACK-005 Friendship Success
Two dog avatars. **Max and Bella are now friends 🐾**. View Bella / Done.

## SCR-PACK-006 Friends
Search only among existing dog friends. Cards: photo/name/breed/age if shared. Actions Share location / Remove friend.

## SCR-PACK-007 Friend Dog
Dog-level allowed profile. Actions Share live location / I'm at the park / Remove friend. Report/Block in overflow. No owner profile.

## SCR-PACK-008 Live Location
Map + select friends + 5/10/15/30/60 min. Explain exact location is visible only to selected dog friends. Active state shows countdown and **Stop sharing**.

## SCR-PACK-009 Community Nearby
Coarse-location map/list. Filter My breed / All. Banner **Approximate locations only**.

## SCR-PACK-010 Community Visibility
Master toggle **Show Max in the community** default OFF. Precision City / Country. Text: **Your exact location is never published in community mode.**

## SCR-PACK-011 I'm at the Park
Title **Let Max's friends know?** Optional message. CTA Send.

## SCR-PACK-012 Walks
Tabs Upcoming / Past. Filter My breed / All. CTA Plan a walk. Cards show place/time/host dog/attendee count.

## SCR-PACK-013 Create Walk
Location/date/time/message/audience + visibility preview. CTA Create walk.

## SCR-PACK-014 Walk Detail
Place/time, host dog, message, map, attending dogs. CTA RSVP; joined state **Going with Max ✓**.

## SCR-PACK-015 RSVP
For multi-dog: **Which dog is coming?** Select dog and confirm.

## SCR-PACK-016 Pack Notifications
Toggles Group walks / Friend at park / Dog news. Native notification permission is requested only when needed.

---

# 10. My Dog

## SCR-DOG-001 Dog Profile
Photo hero + name/breed/age + profile completion + sections Basics / Identification / Health summary / Residence. CTA Edit profile.

## SCR-DOG-002 Edit Dog
Photo, name, breed, sex, DOB/age, size, residence, neuter state. Breed change triggers Journey recalculation confirmation.

## SCR-DOG-003 Travel & ID
Cards: Microchip / Passport or Travel document / Travel readiness / Owner-contact details.

## SCR-DOG-004 Microchip
Number, implant date, implant location, registry, note. Copy action.

## SCR-DOG-005 Travel Documents
Document list + Add document.

## SCR-DOG-006 Travel Document Detail
Type-aware fields. For EU Pet Passport: number, issuing country, issuing vet/authority, issue date, image. Residence can differ from issuer country.

## SCR-DOG-007 Travel Readiness
Origin/destination + checklist based on stored data. Clear official-source disclaimer.

## SCR-DOG-008 Pedigree
Interactive tree centered on current dog. Linked dog vs placeholder styling. CTA Add relative.

## SCR-DOG-009 Add/Link Relative
Mother/Father/Child then Link dog in app / Add placeholder. Relationship confirmation if another owner controls the linked dog.

## SCR-DOG-010 Shows
Results list + Add result.

## SCR-DOG-011 Show Result
Event/date/place/class/result/judge/notes/media.

## SCR-DOG-012 Access & Sharing
Cards Co-owners / Vet sharing / Sharing history.

## SCR-DOG-013 Co-owners
Primary owner + co-owner list. CTA Invite co-owner.

## SCR-DOG-014 Invite Co-owner
QR or secure link. Explain full access until revoked.

## SCR-DOG-015 Vet Share
Active shares with scope/expiry/status/revoke. CTA Share health record.

## SCR-DOG-016 Vet Share Scope
Select health categories + expiry 1h/24h/7d/custom + QR/link generation.

## SCR-DOG-017 Dog Privacy
Community visibility, pedigree visibility, sharing defaults, blocked users/data controls links.

## SCR-DOG-018 Dog Settings
Residence country, delete dog, transfer primary ownership if supported, archive. Separate danger zone.

---

# 11. Multi-Dog

## SCR-MDOG-001 Dog Switcher
Bottom sheet with dog cards and **Add another dog**.

## SCR-MDOG-002 Add Dog
Shortened onboarding: name, breed, age, sex, optional profile. Language/owner/account inherited; country proposed.

## SCR-MDOG-003 Country Change Scope
**Who moved to Germany?** Max only / All my dogs. Note: travel documents are not automatically changed.

---

# 12. Account & Settings

## SCR-ACC-001 Account
Email/auth, language, default country, units, notifications, privacy & safety, subscription, help, legal, delete account.

## SCR-ACC-002 Language
Same picker as onboarding.

## SCR-ACC-003 Default Country
Changes default for future dogs; optional propagation to current dogs.

## SCR-ACC-004 Units
Automatic / Metric / Imperial.

## SCR-ACC-005 Privacy & Safety
Blocked users, community privacy, sharing overview, privacy policy, data export, account deletion.

## SCR-ACC-006 Blocked Users
Safe context + Unblock action.

## SCR-ACC-007 Subscription
States Trial / Active / Grace / Expired / Legacy entitlement. Show store-provided renewal data. Actions Manage subscription / Restore purchases.

## SCR-ACC-008 Help
Searchable FAQ by Health / Travel / Pack / Sharing / Subscription / Privacy + contact support.

## SCR-ACC-009 Delete Account
Explain deletion, co-owned dog impact and subscription handling. Explicit destructive confirmation.

---

# 13. Migration

## SCR-MIG-001 Legacy Offer
In Beagle Owner: **Beagle Owner is growing**. Explain new home and data migration. CTA Move to the new app.

## SCR-MIG-002 Sign In / Link
Use matching account or restore/link legacy purchase.

## SCR-MIG-003 Found Dog
**We found Max** + imported record counts.

## SCR-MIG-004 Import Preview
Grouped checklist + conflicts. CTA Import Max.

## SCR-MIG-005 Import Progress
Resumable; never imply legacy deletion before success.

## SCR-MIG-006 Import Success
**Welcome home, Max.** CTA Go to Today + Check imported data.

---

# 14. Paywall

## SCR-PAY-001 Trial Offer
Title: **Everything Max needs, in one place.**  
Value: Journey, health, Travel & ID, Nearby, Pack, pedigree/sharing.  
Price: **30 days free**, then localized monthly price.  
Clear cancel/renewal terms + Restore purchases.  
CTA **Start free trial**.

## SCR-PAY-002 Trial State
Account/subscription page may show remaining trial days. Avoid countdown anxiety on Today.

## SCR-PAY-003 Expired State
Explain premium requirement while preserving user data. Continue subscription / Manage / permitted export/delete actions.

---

# 15. Empty, Error and Loading States

### Loading
Skeletons, not global spinner.

### Offline
Cached core dog/profile/health summary. Banner: **You're offline. Some information may be out of date.**

### Empty Health
**Max doesn't have any health records yet.** CTA Add first record.

### Empty Pack
**Max's pack starts with the dogs you meet.** CTA Meet a dog.

### Empty Nearby
Offer radius expansion and location check.

### Journey insufficient profile
**Tell us a little more about Max to improve his Journey.** CTA Complete profile.

---

# 16. Permission UX

Never request all permissions on launch.

- Camera → QR scan/document capture
- Location → Nearby/live share/walk map
- Notifications → reminder/social toggle
- Photos/files → upload action

Each native permission prompt gets a pre-permission explanation.

---

# 17. Interaction Rules

- destructive actions require confirmation
- block acts immediately across visibility layers
- live location always shows active indicator/countdown
- community visibility never silently turns on
- dog context always visible on dog-specific actions
- switching dog preserves current tab where safe
- meaningful forms autosave local draft
- dates/times follow locale
- medical history is never removed because breed/profile changes

---

# 18. Recommended Flutter Component Library

```text
DogContextHeader
DogAvatar
DogSwitcherSheet
JourneyHeroCard
JourneyInsightCard
StatusPill
HealthMetricCard
ActionCard
EmptyState
PermissionPrimer
PlaceCard
FriendDogCard
WalkCard
CommunityPrecisionControl
LiveLocationBanner
SecureShareCard
TimelineStageBar
DocumentCard
EntityFormSection
DangerZone
SubscriptionCard
```

Theme:

```text
AppTheme
 ├── colors
 ├── typography
 ├── spacing
 ├── radius
 ├── elevation
 └── motion
```

---

# 19. Route Naming Proposal

```text
/onboarding/*
/today
/journey
/journey/:id
/health
/health/weight
/health/vaccinations
/health/visits
/health/medications
/health/documents
/nearby
/nearby/place/:id
/nearby/emergency
/pack
/pack/meet
/pack/friends
/pack/friend/:dogId
/pack/location
/pack/community
/pack/walks
/pack/walk/:id
/dog/:dogId
/dog/:dogId/travel
/dog/:dogId/pedigree
/dog/:dogId/sharing
/dog/:dogId/shows
/account
/account/privacy
/account/subscription
/migration/*
```

---

# 20. UX Acceptance Criteria

1. User can finish basic onboarding without entering health/weight/microchip.
2. New dog can be added without re-entering owner/language.
3. Current dog is unambiguous on every dog-specific action.
4. Country of residence and passport issuing country are separate.
5. Mixed/unknown dog can receive Journey without fake breed certainty.
6. Community visibility is OFF by default.
7. Exact community location never appears in community UI/backend contract.
8. Live location is clearly temporary and friend-gated.
9. Social does not expose owner profile.
10. QR friendship can be completed quickly after camera access.
11. Today never looks empty.
12. Emergency vet is reachable within two interactions from Today.
13. Health dossier can be shared without unrelated account data.
14. Subscription state and Restore Purchase are always discoverable.
15. Beagle migration is idempotent and cannot duplicate dog records on retry.
16. Blocking applies consistently to map, friends, walks and notifications.
