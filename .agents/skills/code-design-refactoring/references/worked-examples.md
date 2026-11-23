# Worked Examples

Six before/after sketches of the moves that come up most. The pseudocode is deliberately bland so it does not suggest any particular language's style: **always translate into the user's language and idioms** (named arguments, pattern matching, error values, pipelines, comprehensions) rather than mirroring this shape.

## Contents
1. Flattening nested conditionals (guard clauses, control flag, split variable)
2. Comments become names (Extract Method, Extract Variable)
3. A data clump becomes a type that attracts behavior (Introduce Parameter Object)
4. A type code, three ways (data table, polymorphism, leave the match)
5. Reaching through objects (Message Chains, Tell-Don't-Ask)
6. One pattern at three weights (Strategy as function, as object, not at all)

---

## 1. Flattening nested conditionals

**Before**: the happy path is buried; `ok` exists only to reach one exit; `r` means two things.
```
function withdraw(account, amount):
    ok = false
    r = 0
    if account != null:
        if not account.frozen:
            r = account.balance - amount
            if r >= 0:
                account.balance = r
                r = fee(amount)            # r reused for something unrelated
                account.balance = account.balance - r
                ok = true
    return ok
```
**After**: *Replace Nested Conditional with Guard Clauses*, *Remove Control Flag*, *Split Temporary Variable*.
```
function withdraw(account, amount):
    if account == null:     return false
    if account.frozen:      return false

    remaining = account.balance - amount
    if remaining < 0:       return false

    account.balance = remaining - fee(amount)
    return true
```
Check while doing it: every early exit must return what the flag would have held at that point, and no side effect may move across a guard *or across anything that can fail* (a lookup that may throw, a call that may error). Hoisting a computation above a log or write changes what has happened by the time of a crash. Also confirm that each early exit still reports *its own* error: when several checks are flattened into one pipeline with a shared fallback, distinct failures easily collapse into a single message.

## 2. Comments become names

**Before**
```
function invoiceTotal(order):
    # sum the lines
    t = 0
    for line in order.lines:
        t = t + line.price * line.qty
    # loyalty customers with big orders get 5% off
    if order.customer.years > 2 and t > 1000 and not order.customer.suspended:
        t = t * 0.95
    return t
```
**After**: *Extract Method* using the comment as the name; *Extract Variable* (or a query) for the compound condition; *Replace Magic Number*.
```
function invoiceTotal(order):
    subtotal = linesSubtotal(order.lines)
    if qualifiesForLoyaltyDiscount(order.customer, subtotal):
        return subtotal * (1 - LOYALTY_DISCOUNT)
    return subtotal

function qualifiesForLoyaltyDiscount(customer, subtotal):
    return customer.years > LOYALTY_YEARS
       and subtotal > LOYALTY_THRESHOLD
       and not customer.suspended
```
The surviving comment, if any, should say *why* the rule exists, not what the line does.

## 3. A data clump becomes a type that attracts behavior

**Before**: `start, end` travel together everywhere, and every caller re-implements the overlap logic.
```
function bookingsBetween(bookings, start, end): ...
function isAvailable(room, start, end):
    for b in room.bookings:
        if b.start < end and start < b.end:      # duplicated in four places
            return false
    return true
```
**After**: *Introduce Parameter Object*, then *Move Method* into it.
```
type DateRange(start, end):                       # immutable value
    function overlaps(other):  return this.start < other.end and other.start < this.end
    function contains(date):   return this.start <= date and date < this.end

function isAvailable(room, period):
    return none(room.bookings, b -> b.period.overlaps(period))
```
The payoff is not the shorter parameter list; it is that the overlap rule now has one home, and validation (`start <= end`) has somewhere to live. If no behavior ever moves in, you have only made a Data Class, which is still usually an improvement.

## 4. A type code, three ways

**Before**: the same branching on `kind` in two functions.
```
function shippingCost(parcel):
    if parcel.kind == "standard": return 5
    if parcel.kind == "express":  return 12
    if parcel.kind == "freight":  return 40 + parcel.weight * 0.5

function etaDays(parcel):
    if parcel.kind == "standard": return 5
    if parcel.kind == "express":  return 1
    if parcel.kind == "freight":  return 9
```
**Option A, data table.** When variants differ only in *values*, this is the right weight. Do not build a hierarchy for it.
```
SERVICES = { "standard": {base: 5,  perKg: 0,   eta: 5},
             "express":  {base: 12, perKg: 0,   eta: 1},
             "freight":  {base: 40, perKg: 0.5, eta: 9} }

function shippingCost(parcel):
    s = SERVICES[parcel.kind]
    return s.base + parcel.weight * s.perKg
```
**Option B, polymorphism.** When variants differ in *rules*, and new variants keep arriving. One lookup remains, in the factory.
```
interface ShippingService:  cost(parcel), etaDays(parcel)
type Freight implements ShippingService:
    cost(parcel):    return 40 + parcel.weight * 0.5 + customsFee(parcel)
    etaDays(parcel): return 9 + (2 if parcel.international else 0)

function serviceFor(kind): return REGISTRY[kind]       # the one remaining lookup
```
The compiler now catches a forgotten method, but not a forgotten registry entry. Add a test that every known `kind` resolves.
**Option C, keep the branching.** When the set of variants is closed and stable, new *operations* keep arriving, and the language checks exhaustiveness. Make `kind` a proper enum or sum type, remove any catch-all default so that a new variant fails to compile everywhere it matters, and leave the matches alone.

Choosing between B and C is the axis-of-change question (workflow step 6 in SKILL.md).

## 5. Reaching through objects

**Before**: the caller knows the whole path and makes a decision that belongs to someone else.
```
if order.customer.account.creditLimit - order.customer.account.owed >= order.total:
    approve(order)
```
**After**: *Extract Method* on what the caller actually wants, then *Move Method* to where the data lives (Tell, Don't Ask).
```
if order.customer.canAfford(order.total):
    approve(order)

# in Customer:   canAfford(amount): return this.account.availableCredit() >= amount
# in Account:    availableCredit(): return this.creditLimit - this.owed
```
Do not answer a chain by mechanically adding one forwarding method per hop; that produces a Middle Man. Ask what the caller *wanted*, and put that one question on the nearest object. Fluent builders and stream pipelines are not this smell: each step returns the same abstraction, not a deeper internal.

## 6. One pattern at three weights

The need: export a report in one of several formats.

**Not at all.** Two formats, stable for years: a conditional is fine. Stop here.
```
function export(report, format):
    if format == "csv": return toCsv(report)
    return toJson(report)
```
**As a function.** Formats multiply or callers supply their own, and each is a single stateless operation: pass the function.
```
function export(report, formatter):  return formatter(report)
export(report, toCsv)
```
**As an object.** Each variant needs configuration or state, or several related operations, or a name worth having in the design.
```
interface Exporter:  contentType(), fileExtension(), write(report, stream)
type PdfExporter(pageSize, fonts) implements Exporter: ...
```
The same ladder applies to Command (closure, then object once you need undo or serialization), Observer (callback list, then interface), Template Method (higher-order function with step callbacks, then base type), and Factory (function, then hierarchy). Climb a rung only when the current one hurts.
