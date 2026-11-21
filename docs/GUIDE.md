# User guide

How to use Vehicle Maintenance Tracker day to day, and how to set everything up, either yourself in the app or by
asking an AI assistant connected over MCP. Installing it is covered in [DEPLOY.md](DEPLOY.md).

- [The idea in one minute](#the-idea-in-one-minute)
- [First setup checklist](#first-setup-checklist)
- [Vehicles and the odometer](#vehicles-and-the-odometer)
- [Maintenance reminders](#maintenance-reminders)
- [Insurance, registration and other dates](#insurance-registration-and-other-dates)
- [Winter tires and tire sets](#winter-tires-and-tire-sets)
- [Logging a service and receipts](#logging-a-service-and-receipts)
- [Automatic payments](#automatic-payments)
- [Reports and spending](#reports-and-spending)
- [Alerts](#alerts)
- [Chat bots](#chat-bots)
- [Setting up with an AI assistant](#setting-up-with-an-ai-assistant)
- [Glossary](#glossary)

## The idea in one minute

You tell the app **what needs doing and how often** (reminders and dates) and **what you've done** (services and
odometer readings). From that it works out what's coming up:

- **ok**: nothing to do yet;
- **due soon**: inside the warning window you chose (e.g. within 1,000 km or 30 days);
- **overdue**: past the limit;
- **unknown**: it can't tell yet, usually because nothing has been logged for that reminder.

When something becomes *due soon* or *overdue*, you get one alert (in a chat app, if you linked one), and the
Dashboard shows it. Logging the service starts the next cycle.

## First setup checklist

For each vehicle:

1. **Add the vehicle** with today's odometer reading.
2. **Add reminders** for the maintenance you care about (oil, tire rotation, brakes, filters...), with *when it
   was last done* if you know.
3. **Add dates**: insurance renewal, registration renewal, inspections.
4. **Winter tires?** Add the winter-tire reminders and your tire sets.
5. **Automatic payments?** Add them (monthly insurance, financing, parking...).
6. Optional: **link Telegram or Discord** (Settings → Chat apps) to get alerts and text your km.

An AI assistant can do steps 1 to 5 for you; see [Setting up with an AI assistant](#setting-up-with-an-ai-assistant).

## Vehicles and the odometer

**Vehicles → Add vehicle**: a nickname (how you'll refer to it, e.g. "Civic"; unique per account), make, model,
year and optionally the VIN.

**Odometer readings** feed the km-based reminders: the app estimates when a km limit will be reached from your
average km/day over the last 90 days. Log a reading whenever it's convenient:

- the vehicle's **Odometer** tab, or **Quick log** (the button at the bottom right);
- text the number to the chat bot (`84500`);
- logging a service with its odometer reading also counts.

The odometer can't go backwards. If an earlier reading was wrong, log the right one with **Yes, this is a
correction**: the higher readings are marked wrong (they stay in the history). A correction itself can't be
deleted.

**Odometer nudge.** If a vehicle with km reminders gets no reading for 2 weeks, the chat bot asks for one at
18:00. Change the interval or turn it off on the vehicle's *Odometer* tab (*Ask me for the km*).

**Archive** a vehicle you sold (Settings → Vehicles): it disappears from the lists, its history is kept, and
its automatic payments end.

## Maintenance reminders

Vehicle → **Reminders** tab → **Add reminder**:

| Field | Meaning |
|---|---|
| Service | What it's for: oil change, tire rotation, brake inspection, engine air filter, cabin air filter, battery, wheel alignment, transmission fluid, coolant, spark plugs, brake fluid, wiper blades, or your own service (type a name and pick **+ Add "..."**). |
| Every (km) | The km interval, e.g. 8,000. |
| Every (months) | The time interval, e.g. 12. Give km, months or both: **whichever comes first** wins. |
| Warn at (km before) / (days before) | How early it turns *due soon*. Defaults: 1,000 km and 30 days. |
| When was this last done? | Date and/or km of the last time, if you know. Used until you log a service for it. Without it (and without a logged service) the reminder shows *unknown*. |

One reminder per service per vehicle. Typical starting points (check your owner's manual):

| Service | Typical interval |
|---|---|
| Oil change | 8,000 km or 12 months (synthetic); 5,000 km or 6 months (conventional) |
| Tire rotation | 10,000 km or 12 months |
| Brake inspection | 12 months |
| Engine air filter | 25,000 km or 24 months |
| Cabin air filter | 20,000 km or 12 months |
| Brake fluid | 36 months |
| Coolant | 100,000 km or 60 months |
| Spark plugs | 100,000 km |

When it's done, press **Done today** on the item (it logs the service at today's km), or log the service with its
details (see below).

## Insurance, registration and other dates

Vehicle → **Reminders** tab → **Add date**:

| Field | Meaning |
|---|---|
| Type | **Insurance** (renewal), **Registration** (renewal, e.g. SAAQ or DMV) or **Other** (give it a title, e.g. "Safety inspection", "Emissions test", "Warranty ends"). |
| Due date | The next due date. |
| Repeats every year | After you mark it done, it moves to the same date next year. |
| Warn this many days ahead | When it turns *due soon* and alerts. |

Press **Mark done** once it's renewed. If you pay insurance or registration monthly, also add the payment under
[Automatic payments](#automatic-payments): the date reminds you of the renewal, the payment counts the money.

## Winter tires and tire sets

**Winter-tire reminders:** vehicle → **Reminders** → **Add winter-tire reminders** adds two yearly dates:
*Install winter tires by Dec 1* (alerts 30 days ahead) and *Winter tires can come off after Mar 15* (shown, no
alert). These follow Quebec's rules; elsewhere, add your own dates with **Add date** instead. Marking either done
asks which tire set is now on the car.

**Tire sets:** the **Tires** page → **Add set**: a label ("Winters"), the season (winter, summer, all-season),
size (e.g. `215/55R17`), brand, DOT code, purchase date and cost (counted in spending) and where it's stored.
**Mount** marks the set that's on the car; **Add tread reading** records tread depth, and the app warns when a
set gets close to the legal minimum.

## Logging a service and receipts

**Quick log** (bottom right) → *Service*, or the vehicle's **Services** tab → **Log service**:

- **What was done?**: one or more services (type to add your own);
- **Date**, **Odometer (km)** at the visit, **Shop / vendor**, **Total cost** (taxes included) and notes;
- **receipts**: photos (JPEG, PNG, WebP, HEIC) or PDFs up to 20 MB each.

With several services in one visit you can split the cost between them; otherwise it's shared out for the
reports. You can also send a receipt photo to the chat bot: it attaches it to a service from the last 7 days, or
saves it as a receipt-only entry you can fill in later.

## Automatic payments

Vehicle → **Payments** tab → **Add payment**, for money taken automatically: insurance, financing or lease,
registration, parking...

- the amount, how often (every 1, 3, 6 or 12 months), the first payment (it sets the day of the month) and,
  optionally, the last one;
- each payment counts as spent on its date, with nothing to confirm; upcoming ones show as *scheduled*;
- **Change amount...** starts a new price from a date and keeps the earlier payments at the old one;
- yearly payments can alert a set number of days before they renew. Monthly debits never alert.

## Reports and spending

**Reports** shows what you spent in a period (this month, last month, this year, last year, the last 12 months
or a custom range), filtered by vehicle and category: a monthly chart, a breakdown by category, every entry
(click one to open it) and a `spending.csv` export of what's on screen. Services, tire purchases and automatic
payments are all included. The filters are in the address bar, so a view can be bookmarked.

## Alerts

An alert goes out **once** when an item moves into *due soon* and once more if it becomes *overdue*. Alerts are
checked every morning at 08:00 and right after you change something.

- **Done today** logs the service at the current km; **Snooze 7 d** silences it for a week, after which a still
  due item alerts once more.
- With both Telegram and Discord linked, choose where alerts go in Settings → Chat apps → *Send alerts to*.
- Without a linked chat app, alerts wait (up to a week) until you link one; the Dashboard always shows them.

## Chat bots

Link them in Settings → **Chat apps** (the server owner must set them up first, see
[DEPLOY.md](DEPLOY.md#telegram-and-discord-bots)). Then, in a direct message:

| You send | What happens |
|---|---|
| `84500`, `84,500 km`, `84 500`, `84.5k` | Logs mileage. With several vehicles it picks the one whose current km is closest below, with a **Wrong vehicle** button. |
| `civic 84500` | Logs it for that vehicle (the nickname wins). |
| A lower number | Asks whether it's a correction. |
| A jump of more than 5,000 km | Asks you to confirm. |
| A photo or PDF | Files it as a receipt (see above). |
| `/due` (Telegram) or `!due` (Discord) | What needs attention. |
| `/vehicles` or `!vehicles` | Current km of each vehicle. |
| `/help` or `!help` | This list. |

## Setting up with an AI assistant

If the server has MCP turned on and you've connected an assistant ([DEPLOY.md](DEPLOY.md#ai-assistants-mcp)),
you can just describe your car. For example:

> I have a 2019 Honda Civic at 84,500 km. Synthetic oil every 8,000 km or a year, last changed in August at
> 80,000 km. Tire rotation every 10,000 km. Insurance with Desjardins renews March 1, $142 a month on the 15th.
> Registration is due in April. I put winter tires on every year; my winters are 215/55R17 Michelin X-Ice,
> stored at my parents'.

The assistant asks about anything missing, then calls the tools below. It can **read and add**, never edit or
delete: changes and deletions are done in the app.

| To... | Tool | Key inputs |
|---|---|---|
| See vehicles and current km | `list_vehicles` | |
| See what's due | `whats_due` | vehicle (optional) |
| See history | `service_history` | vehicle, limit |
| See spending | `spending` | start, end, vehicle, categories |
| Know valid service names | `list_service_types` | |
| Add a vehicle | `add_vehicle` | nickname, make, model, year, current_km |
| Add a maintenance reminder | `add_reminder` | vehicle, service, every_km and/or every_months, warn_km, warn_days, last_done_date, last_done_km |
| Add insurance / registration / other date | `add_date` | kind (`insurance`, `registration`, `custom`), due_date, vehicle, title (for custom), yearly, warn_days |
| Add the winter-tire dates | `add_winter_tire_reminders` | vehicle |
| Add a tire set | `add_tire_set` | vehicle, label, season (`winter`, `summer`, `all_season`), size, brand_model, purchase_date, cost, storage_location |
| Add an automatic payment | `add_recurring_payment` | vehicle, name, category, amount, every_months (1, 3, 6, 12), first_payment, last_payment, remind_days_before (yearly only) |
| Log a reading | `log_odometer` | vehicle, km (lower = `correction`, +5,000 km = `confirm_big_jump`; it asks you first) |
| Log a service | `log_service` | vehicle, date, services, cost, vendor, odometer_km, notes |
| Keep a receipt file | `attach_receipt` or `receipt_upload_link` | service_id |

**Receipts:** show the assistant a photo of a receipt and ask it to log it. It reads the date, total, shop,
odometer and work done, checks with you, and logs the service. To keep the file it gives you a one-time upload
link (valid 15 minutes), since most assistants can't pass the image on themselves.

**Good to know**

- Amounts are in dollars, distances in km, dates as `YYYY-MM-DD`.
- `vehicle` is the nickname (any case) or the id.
- Service names must match `list_service_types`; anything else goes in the notes, or add it as your own service
  in the app first (Settings → Your services).
- For a policy paid monthly: `add_date(kind="insurance")` for the yearly renewal **and**
  `add_recurring_payment(every_months=1)` for the payments.

## Glossary

| Term | Meaning |
|---|---|
| Reminder (rule) | Recurring maintenance by km and/or months, tied to a service. |
| Date | A one-off or yearly date: insurance, registration, inspection, winter tires. |
| Service | A visit or job you logged, with date, km, cost, vendor and receipts. |
| Correction | An odometer reading that replaces wrong, higher readings. |
| Automatic payment | Money taken on a schedule, counted as spent on each date. |
| Owner | The first account; can invite people and use AI assistants by default. |
