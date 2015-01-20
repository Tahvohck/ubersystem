from uber.common import *

def check_everything(attendee):
    if MODE == 'magstock':
        shirt_size_selected = attendee.shirt != NO_SHIRT
        shirt_color_selected = attendee.shirt_color != NO_SHIRT
        if shirt_size_selected != shirt_color_selected:
            return 'Shirt color/size not valid combination. Either set both or remove both'

    if AT_THE_CON and attendee.id is None:
        if isinstance(attendee.badge_num, str) or attendee.badge_num < 0:
            if MODE != 'magstock':
                return 'Invalid badge number'
            else:
                attendee.badge_num = next_badge_num(attendee.badge_type)

        if attendee.id is None and attendee.badge_num != 0 and attendee.session.query(Attendee).filter_by(badge_type=attendee.badge_type, badge_num=attendee.badge_num).count():
            return 'Another attendee already exists with that badge number'

    if attendee.is_dealer and not attendee.group:
        return 'Dealers must be associated with a group'

    message = check(attendee)
    if message:
        return message

    if AT_THE_CON and attendee.age_group == AGE_UNKNOWN and attendee.is_new:
        return "You must enter this attendee's age group"


@all_renderable(PEOPLE, REG_AT_CON)
class Root:
    def index(self, session, message='', page='1', search_text='', uploaded_id='', order='last_first'):
        total_count = session.query(Attendee).count()
        count = 0
        if search_text:
            attendees = session.search(search_text)
            count = attendees.count()
        if not count:
            attendees = session.query(Attendee).options(joinedload(Attendee.group))
            count = total_count

        attendees = attendees.order(order)

        groups = set()
        for a in session.query(Attendee) \
                        .filter(Attendee.first_name == '', Attendee.group_id != None) \
                        .options(joinedload(Attendee.group)).all():
            short_group_name = a.group.name[:20] + "..." if len(a.group.name) > 23 else a.group.name
            groups.add((a.group.id, short_group_name + (' ({})'.format(a.group.leader.full_name) if a.group.leader else '')))

        if search_text and count == total_count:
            message = 'No matches found'
        elif search_text and count == 1 and (not AT_THE_CON or search_text.isdigit()):
            raise HTTPRedirect('form?id={}&message={}', attendees.one().id, 'This attendee was the only search result')

        page = int(page)
        pages = range(1, int(math.ceil(count / 100)) + 1)
        attendees = attendees[-100 + 100*page : 100*page]

        return {
            'message':        message if isinstance(message, str) else message[-1],
            'page':           page,
            'pages':          pages,
            'search_text':    search_text,
            'search_results': bool(search_text),
            'attendees':      attendees,
            'groups':         sorted(groups, key = lambda tup: tup[1]),
            'order':          Order(order),
            'attendee_count': total_count,
            'checkin_count':  session.query(Attendee).filter(Attendee.checked_in == None).count(),
            'attendee':       session.attendee(uploaded_id) if uploaded_id else None,
            'remaining_badges': max(0, MAX_BADGE_SALES - state.BADGES_SOLD)
        }

    def form(self, session, message='', return_to='', omit_badge='', **params):
        attendee = session.attendee(params, checkgroups=['interests','requested_depts','assigned_depts'],
                                    bools=['staffing','trusted','international','placeholder','got_merch','can_spam'])
        if 'first_name' in params:
            attendee.group_id = params['group_opt'] or None
            if AT_THE_CON and omit_badge:
                attendee.badge_num = 0
            if 'no_override' in params:
                attendee.overridden_price = None

            message = check_everything(attendee)
            if not message:
                session.add(attendee)
                if return_to:
                    raise HTTPRedirect(return_to + '&message={}', 'Attendee data uploaded')
                else:
                    raise HTTPRedirect('index?uploaded_id={}&message={}&search_text={}', attendee.id, 'has been uploaded',
                        '{} {}'.format(attendee.first_name, attendee.last_name) if AT_THE_CON else '')

        return {
            'message':    message,
            'attendee':   attendee,
            'return_to':  return_to,
            'omit_badge': omit_badge,
            'group_opts': [(g.id, g.name) for g in session.query(Group).order_by(Group.name).all()],
            'unassigned': {group_id: unassigned
                           for group_id, unassigned in session.query(Attendee.group_id, func.count('*'))
                                                              .filter(Attendee.group_id != None, Attendee.first_name == '')
                                                              .group_by(Attendee.group_id).all()}
        }

    def change_badge(self, session, id, message='', **params):
        attendee = session.attendee(id)
        if 'badge_type' in params:
            preassigned = AT_THE_CON or attendee.badge_type in PREASSIGNED_BADGE_TYPES
            if preassigned:
                message = check(attendee)

            if not message:
                message = session.change_badge(attendee, params['badge_type'], params.get('newnum') or 0)
                raise HTTPRedirect('form?id={}&message={}', attendee.id, message)

        return {
            'message':  message,
            'attendee': attendee
        }

    def history(self, session, id):
        attendee = session.attendee(id)
        return {
            'attendee': attendee,
            'emails':   session.query(Email)
                               .filter(or_(Email.dest == attendee.email,
                                           and_(Email.model == 'Attendee', Email.fk_id == id)))
                               .order_by(Email.when).all(),
            'changes':  session.query(Tracking)
                               .filter(or_(Tracking.links.like('%attendee({})%'.format(id)),
                                           and_(Tracking.model == 'Attendee', Tracking.fk_id == id)))
                               .order_by(Tracking.when).all()
        }

    @csrf_protected
    def delete(self, session, id, return_to = 'index?'):
        attendee = session.attendee(id)
        if attendee.group:
            if attendee.group.leader_id == attendee.id:
                message = 'You cannot delete the leader of a group; you must make someone else the leader first, or just delete the entire group'
            else:
                session.add(Attendee(**{attr: getattr(attendee, attr) for attr in [
                    'group', 'registered', 'badge_type', 'badge_num', 'paid', 'amount_paid', 'amount_extra'
                ]}))
                session.delete_from_group(attendee, attendee.group)
                message = 'Attendee deleted, but this ' + attendee.badge + ' badge is still available to be assigned to someone else in the same group'
        else:
            session.delete(attendee)
            message = 'Attendee deleted'

        raise HTTPRedirect(return_to + ('' if return_to[-1] == '?' else '&') + 'message={}', message)

    def goto_volunteer_checklist(self, id):
        cherrypy.session['staffer_id'] = id
        raise HTTPRedirect('../signups/index')

    @ajax
    def record_mpoint_cashout(self, session, badge_num, amount):
        try:
            attendee = session.attendee(badge_num=badge_num)
        except:
            return {'success': False, 'message': 'No one has badge number {}'.format(badge_num)}

        mfc = MPointsForCash(attendee=attendee, amount=amount)
        message = check(mfc)
        if message:
            return {'success': False, 'message': message}
        else:
            session.add(mfc)
            session.commit()
            message = '{mfc.attendee.full_name} exchanged {mfc.amount} MPoints for cash'.format(mfc=mfc)
            return {'id': mfc.id, 'success': True, 'message': message}

    @ajax
    def undo_mpoint_cashout(self, session, id):
        session.delete(session.mpoints_for_cash(id))
        return 'MPoint usage deleted'

    @ajax
    def record_old_mpoint_exchange(self, session, badge_num, amount):
        try:
            attendee = session.attendee(badge_num=badge_num)
        except:
            return {'success': False, 'message': 'No one has badge number {}'.format(badge_num)}

        ome = OldMPointExchange(attendee=attendee, amount=amount)
        message = check(ome)
        if message:
            return {'success': False, 'message': message}
        else:
            session.add(ome)
            session.commit()
            message = "{ome.attendee.full_name} exchanged {ome.amount} of last year's MPoints".format(ome=ome)
            return {'id': ome.id, 'success': True, 'message': message}

    @ajax
    def undo_mpoint_exchange(self, session, id):
        session.delete(session.old_m_point_exchange(id))
        session.commit()
        return 'MPoint exchange deleted'

    @ajax
    def record_sale(self, session, badge_num=None, **params):
        params['reg_station'] = cherrypy.session.get('reg_station')
        sale = session.sale(params)
        message = check(sale)
        if not message and badge_num is not None:
            try:
                sale.attendee = Attendee.objects.get(badge_num=badge_num)
            except:
                message = 'No attendee has that badge number'

        if message:
            return {'success': False, 'message': message}
        else:
            session.add(sale)
            session.commit()
            message = '{sale.what} sold{to} for ${sale.cash}{mpoints}' \
                      .format(sale=sale,
                              to=(' to ' + sale.attendee.full_name) if sale.attendee else '',
                              mpoints=' and {} MPoints'.format(sale.mpoints) if sale.mpoints else '')
            return {'id': sale.id, 'success': True, 'message': message}

    @ajax
    def undo_sale(self, session, id):
        session.delete(session.sale(id))
        return 'Sale deleted'

    @ajax
    def check_in(self, session, id, badge_num, age_group, group, message=''):
        attendee = session.attendee(id)
        pre_badge = attendee.badge_num
        success, increment = True, False

        if not attendee.badge_num:
            if MODE == 'magstock':
                if not badge_num or badge_num == 0:
                    badge_num = next_badge_num(attendee.badge_type)

            message = check_range(badge_num, attendee.badge_type)
            if not message:
                maybe_dupe = session.query(Attendee).filter_by(badge_num=badge_num, badge_type=attendee.badge_type)
                if maybe_dupe.count():
                    message = 'That badge number already belongs to ' + maybe_dupe.first().full_name

            if group:
                session.match_to_group(attendee, session.group(group))
            elif attendee.paid == PAID_BY_GROUP and not attendee.group:
                message = 'You must select a group for this attendee.'

            success = not message

        if success and attendee.checked_in:
            message = attendee.full_name + ' was already checked in!'
        elif success:
            message = ""
            attendee.checked_in = datetime.now(UTC)
            attendee.age_group = int(age_group)
            if not attendee.badge_num:
                attendee.badge_num = int(badge_num)
            if attendee.paid == NOT_PAID:
                attendee.paid = HAS_PAID
                attendee.amount_paid = attendee.total_cost
                message = '<b>This attendee has not paid for their badge; make them pay ${0}!</b> <br/>'.format(attendee.total_cost)
            session.add(attendee)
            session.commit()
            increment = True
            message += '{0.full_name} checked in as {0.badge} with {0.accoutrements}'.format(attendee)

        return {
            'success':    success,
            'message':    message,
            'increment':  increment,
            'badge':      attendee.badge,
            'paid':       attendee.paid_label,
            'age_group':  attendee.age_group_label,
            'pre_badge':  pre_badge,
            'checked_in': attendee.checked_in and hour_day_format(attendee.checked_in)
        }

    @csrf_protected
    def undo_checkin(self, session, id, pre_badge):
        attendee = session.attendee(id)
        attendee.checked_in, attendee.badge_num = None, pre_badge
        session.add(attendee)
        session.commit()
        return 'Attendee successfully un-checked-in'

    def recent(self, session):
        return {'attendees': session.query(Attendee).order_by(Attendee.registered.desc())}

    def merch(self, message=''):
        return {'message': message}

    def multi_merch_pickup(self, session, message="", csrf_token=None, picker_upper=None, badges=()):
        picked_up = []
        if csrf_token:
            check_csrf(csrf_token)
            try:
                picker_upper = session.query(Attendee).filter_by(badge_num=int(picker_upper)).one()
            except:
                message = 'Please enter a valid badge number for the person picking up the merch: {} is not in the system'.format(picker_upper)
            else:
                for badge_num in set(badges):
                    if badge_num:
                        try:
                            attendee = session.query(Attendee).filter_by(badge_num=int(badge_num)).one()
                        except:
                            picked_up.append('{!r} is not a valid badge number'.format(badge_num))
                        else:
                            if attendee.got_merch:
                                picked_up.append('{a.full_name} (badge {a.badge_num}) already got their merch'.format(a=attendee))
                            else:
                                attendee.got_merch = True
                                picked_up.append('{a.full_name} (badge {a.badge_num}): {a.merch}'.format(a=attendee))
                                session.add(MerchPickup(picked_up_by=picker_upper, picked_up_for=attendee))
                session.commit()

        return {
            'message': message,
            'picked_up': picked_up,
            'picker_upper': picker_upper
        }

    def lost_badge(self, session, id):
        a = session.attendee(id)
        a.for_review += "Automated message: Badge reported lost on {}. Previous payment type: {}.".format(localized_now().strftime('%m/%d, %H:%M'),a.paid_label)
        a.paid = LOST_BADGE
        session.add(a)
        session.commit()
        raise HTTPRedirect('index?message={}', 'Badge has been recorded as lost.')

    @ajax
    def check_merch(self, session, badge_num):
        id = shirt = None
        if not (badge_num.isdigit() and 0 < int(badge_num) < 99999):
            message = 'Invalid badge number'
        else:
            results = session.query(Attendee).filter_by(badge_num=badge_num)
            if results.count() != 1:
                message = 'No attendee has badge number {}'.format(badge_num)
            else:
                attendee = results.one()
                if not attendee.merch:
                    message = '{a.full_name} ({a.badge}) has no merch'.format(a = attendee)
                elif attendee.got_merch:
                    message = '{a.full_name} ({a.badge}) already got {a.merch}'.format(a = attendee)
                else:
                    id = attendee.id
                    shirt = (attendee.shirt or SIZE_UNKNOWN) if attendee.gets_shirt else NO_SHIRT
                    message = '{a.full_name} ({a.badge}) has not yet received {a.merch}'.format(a=attendee)
        return {
            'id': id,
            'shirt': shirt,
            'message': message
        }

    @ajax
    def give_merch(self, session, id, shirt_size, no_shirt):
        try:
            shirt_size = int(shirt_size)
        except:
            shirt_size = None

        success = False
        attendee = session.attendee(id)
        if not attendee.merch:
            message = '{} has no merch'.format(attendee.full_name)
        elif attendee.got_merch:
            message = '{} already got {}'.format(attendee.full_name, attendee.merch)
        elif shirt_size == SIZE_UNKNOWN:
            message = 'You must select a shirt size'
        else:
            if no_shirt:
                message = '{} is now marked as having received all of the following (EXCEPT FOR THE SHIRT): {}'
            else:
                message = '{} is now marked as having received {}'
            message = message.format(attendee.full_name, attendee.merch)
            attendee.got_merch = True
            if shirt_size:
                attendee.shirt = shirt_size
            if no_shirt:
                session.add(NoShirt(attendee=attendee))
            success = True
            session.commit()

        return {
            'id': id,
            'success': success,
            'message': message
        }

    @ajax
    def take_back_merch(self, session, id):
        attendee = session.attendee(id)
        attendee.got_merch = False
        if attendee.no_shirt:
            session.delete(attendee.no_shirt)
        session.commit()
        return '{a.full_name} ({a.badge}) merch handout canceled'.format(a=attendee)

    if AT_THE_CON or DEV_BOX:
        @unrestricted
        def register(self, session, message='', **params):
            params['id'] = 'None'
            attendee = session.attendee(params, bools=['international'], checkgroups=['interests'], restricted=True, ignore_csrf=True)
            if 'first_name' in params:
                if not attendee.payment_method:
                    message = 'Please select a payment type'
                elif not attendee.first_name or not attendee.last_name:
                    message = 'First and Last Name are required fields'
                elif attendee.ec_phone[:1] != '+' and not attendee.international and len(re.compile('[0-9]').findall(attendee.ec_phone)) != 10:
                    message = 'Enter a 10-digit emergency contact number'
                elif re.search(SAME_NUMBER_REPEATED, re.sub(r'[^0-9]', '', attendee.ec_phone)):
                    message = 'Please enter a real emergency contact number'
                elif attendee.age_group == AGE_UNKNOWN:
                    message = 'Please select an age category'
                elif attendee.payment_method == MANUAL and not attendee.email:
                    message = 'Email address is required to pay with a credit card at our registration desk'
                elif attendee.badge_type not in [ATTENDEE_BADGE, ONE_DAY_BADGE]:
                    message = 'No hacking allowed!'
                else:
                    if params.get('under_13') and attendee.age_group == UNDER_18:
                        attendee.for_review += 'Automated message: Attendee marked as under 13 during registration.'
                    attendee.badge_num = 0
                    if not attendee.zip_code:
                        attendee.zip_code = '00000'
                    message = 'Thanks!  Please queue in the {} line and have your photo ID and {} ready.'
                    if attendee.payment_method == STRIPE:
                        raise HTTPRedirect('pay?id={}', attendee.id)
                    elif attendee.payment_method == GROUP:
                        message = 'Please proceed to the preregistration line to pick up your badge.'
                        attendee.paid = PAID_BY_GROUP
                    elif attendee.payment_method == CASH:
                        message = message.format('cash', '${}'.format(attendee.total_cost))
                    elif attendee.payment_method == MANUAL:
                        message = message.format('credit card', 'credit card')
                    session.add(attendee)
                    raise HTTPRedirect('register?message={}', message)

            return {
                'message':  message,
                'attendee': attendee
            }

        @unrestricted
        def pay(self, session, id, message=''):
            attendee = session.attendee(id)
            if attendee.paid == HAS_PAID:
                raise HTTPRedirect('register?message={}', 'You are already paid and should proceed to the preregistration desk to pick up your badge')
            else:
                return {
                    'message': message,
                    'attendee': attendee,
                    'charge': Charge(attendee, description=attendee.full_name)
                }

        @unrestricted
        @credit_card
        def take_payment(self, session, payment_id, stripeToken):
            charge = Charge.get(payment_id)
            [attendee] = charge.attendees
            message = charge.charge_cc(stripeToken)
            if message:
                raise HTTPRedirect('pay?id={}&message={}', attendee.id, message)
            else:
                attendee.paid = HAS_PAID
                attendee.amount_paid = attendee.total_cost

                # HACK! need to fix this to save correctly.
                if attendee.registered is None:
                    attendee.registered = datetime.now()

                session.add(attendee)
                raise HTTPRedirect('register?message={}', 'Your payment has been accepted, please proceed to the Preregistration desk to pick up your badge')

    def comments(self, session, order='last_name'):
        return {
            'order': Order(order),
            'attendees': session.query(Attendee).filter(Attendee.comments != '').order_by(order).all()
        }

    def new(self, session, show_all='', message='', checked_in=''):
        if 'reg_station' not in cherrypy.session:
            raise HTTPRedirect('new_reg_station')

        groups = set()
        for a in session.query(Attendee).filter(Attendee.first_name == '', Attendee.group_id != None) \
                                        .options(joinedload(Attendee.group)).all():
            groups.add((a.group.id, a.group.name or 'BLANK'))

        if show_all:
            restrict_to = [Attendee.paid == NOT_PAID, Attendee.placeholder == False]
        else:
            restrict_to = [Attendee.registered > datetime.now(UTC) - timedelta(minutes=90)]

        return {
            'message':    message,
            'show_all':   show_all,
            'checked_in': checked_in,
            'groups':     sorted(groups, key = lambda tup: tup[1]),
            'recent':     session.query(Attendee).filter(Attendee.badge_num == 0, Attendee.first_name != '', *restrict_to)
                                                 .order_by(Attendee.registered).all(),
            'remaining_badges': max(0, MAX_BADGE_SALES - state.BADGES_SOLD)
        }

    def new_reg_station(self, reg_station='', message=''):
        if reg_station:
            if not reg_station.isdigit() or not (0 <= int(reg_station) < 100):
                message = 'Reg station must be a positive integer between 0 and 100'

            if not message:
                cherrypy.session['reg_station'] = int(reg_station)
                raise HTTPRedirect('new?message={}', 'Reg station number recorded')

        return {
            'message': message,
            'reg_station': reg_station
        }

    @csrf_protected
    def mark_as_paid(self, session, id, payment_method):
        if cherrypy.session['reg_station'] == 0:
            raise HTTPRedirect('new_reg_station?message={}', 'Reg station 0 is for prereg only and may not accept payments')
        elif int(payment_method) == MANUAL:
            raise HTTPRedirect('manual_reg_charge_form?id={}', id)

        attendee = session.attendee(id)
        attendee.paid = HAS_PAID
        if int(payment_method) == STRIPE_ERROR:
            attendee.for_review += "Automated message: Stripe payment manually verified by admin."
        attendee.payment_method = payment_method
        attendee.amount_paid = attendee.total_cost
        attendee.reg_station = cherrypy.session['reg_station']
        raise HTTPRedirect('new?message={}', 'Attendee marked as paid')

    def manual_reg_charge_form(self, session, id):
        attendee = session.attendee(id)
        if attendee.paid != NOT_PAID:
            raise HTTPRedirect('new?message={}{}', attendee.full_name, ' is already marked as paid')

        return {
            'attendee': attendee,
            'charge': Charge(attendee)
        }

    # TODO: need to fix this Charge stuff
    @credit_card
    def manual_reg_charge(self, session, payment_id, stripeToken):
        charge = Charge.get(payment_id)
        [attendee] = charge.attendees
        message = charge.charge_cc(stripeToken)
        if message:
            raise HTTPRedirect('new_credit_form?id={}&message={}', attendee.id, message)
        else:
            attendee.paid = HAS_PAID
            attendee.amount_paid = attendee.total_cost
            raise HTTPRedirect('new?message={}', 'Payment accepted')

    @csrf_protected
    def new_checkin(self, session, id, badge_num, ec_phone='', message='', group=''):
        checked_in = ''
        badge_num = int(badge_num) if badge_num.isdigit() else 0
        attendee = session.attendee(id)

        if MODE == 'magstock' and not badge_num:
            badge_num = next_badge_num(attendee.badge_type)

        existing = session.query(Attendee).filter_by(badge_num=badge_num).all()
        if 'reg_station' not in cherrypy.session:
            raise HTTPRedirect('new_reg_station')
        elif not badge_num:
            message = "You didn't enter a valid badge number"
        elif existing:
            message = '{a.badge} already belongs to {a.full_name}'.format(a=existing[0])
        else:
            badge_type, message = get_badge_type(badge_num)
            if not message:
                attendee.badge_type, attendee.badge_num = badge_type, badge_num
                if group:
                    session.match_to_group(attendee, session.group(group))
                elif attendee.paid != HAS_PAID:
                    message = 'You must mark this attendee as paid before you can check them in'

        if not message:
            attendee.ec_phone = ec_phone
            attendee.checked_in = datetime.now(UTC)
            attendee.reg_station = cherrypy.session['reg_station']
            message = '{a.full_name} checked in as {a.badge} with {a.accoutrements}'.format(a = attendee)
            checked_in = attendee.id

        raise HTTPRedirect('new?message={}&checked_in={}', message, checked_in)

    @unrestricted
    def arbitrary_charge_form(self, message='', amount=None, description=''):
        charge = None
        if amount is not None:
            if not amount.isdigit() or not (1 <= int(amount) <= 999):
                message = 'Amount must be a dollar amount between $1 and $999'
            elif not description:
                message = "You must enter a brief description of what's being sold"
            else:
                charge = Charge(amount = 100 * int(amount), description = description)

        return {
            'charge': charge,
            'message': message,
            'amount': amount,
            'description': description
        }

    @unrestricted
    @credit_card
    def arbitrary_charge(self, session, payment_id, stripeToken):
        charge = Charge.get(payment_id)
        message = charge.charge_cc(stripeToken)
        if message:
            raise HTTPRedirect('arbitrary_charge_form?message={}', message)
        else:
            session.add(ArbitraryCharge(
                amount = charge.dollar_amount,
                what = charge.description,
                reg_station = cherrypy.session.get('reg_station')
            ))
            raise HTTPRedirect('arbitrary_charge_form?message={}', 'Charge successfully processed')

    def reg_take_report(self, session, **params):
        if params:
            start = EVENT_TIMEZONE.localize(datetime.strptime('{startday} {starthour}:{startminute}'.format(**params), '%Y-%m-%d %H:%M'))
            end = EVENT_TIMEZONE.localize(datetime.strptime('{endday} {endhour}:{endminute}'.format(**params), '%Y-%m-%d %H:%M'))
            sales = session.query(Sale).filter(Sale.reg_station == params['reg_station'],
                                               Sale.when > start, Sale.when <= end).all()
            attendees = session.query(Attendee).filter(Attendee.reg_station == params['reg_station'], Attendee.amount_paid > 0,
                                                       Attendee.registered > start, Attendee.registered <= end).all()
            params['sales'] = sales
            params['attendees'] = attendees
            params['total_cash'] = sum(a.amount_paid for a in attendees if a.payment_method == CASH) \
                                 + sum(s.cash for s in sales if s.payment_method == CASH)
            params['total_credit'] = sum(a.amount_paid for a in attendees if a.payment_method in [STRIPE, SQUARE, MANUAL]) \
                                   + sum(s.cash for s in sales if s.payment_method == CREDIT)
        else:
            params['endday'] = localized_now().strftime('%Y-%m-%d')
            params['endhour'] = localized_now().strftime('%H')
            params['endminute'] = localized_now().strftime('%M')

        stations = sorted(filter(bool, Attendee.objects.values_list('reg_station', flat=True).distinct()))
        params['reg_stations'] = stations
        params.setdefault('reg_station', stations[0] if stations else 0)
        return params

    def undo_new_checkin(self, session, id):
        attendee = session.attendee(id)
        if attendee.group:
            session.add(Attendee(group=attendee.group, paid=PAID_BY_GROUP, badge_type=attendee.badge_type, ribbon=attendee.ribbon))
        attendee.badge_num = 0
        attendee.checked_in = attendee.group = None
        raise HTTPRedirect('new?message={}', 'Attendee un-checked-in')

    def shifts(self, session, id, shift_id='', message=''):
        attendee = session.attendee(id)
        return {
            'message':  message,
            'shift_id': shift_id,
            'attendee': attendee,
            'possible': attendee.possible_opts,
            'shifts':   Shift.dump(attendee.shifts),
            'jobs':     [(job.id, '({}) [{}] {}'.format(custom_tags.timespan.pretty(job), job.location_label, job.name))
                         for job in session.query(Job)
                                           .outerjoin(Job.shifts)
                                           .filter(Job.start_time > localized_now() - timedelta(hours=2),
                                                   *([] if attendee.trusted else [Job.restricted == False]))
                                           .group_by(Job.id)
                                           .having(func.count(Shift.id) < Job.slots)
                                           .order_by(Job.start_time, Job.location).all()]
        }

    @csrf_protected
    def update_nonshift(self, session, id, nonshift_hours):
        attendee = session.attendee(id)
        if not re.match('^[0-9]+$', nonshift_hours):
            raise HTTPRedirect('shifts?id={}&message={}', attendee.id, 'Invalid integer')
        else:
            attendee.nonshift_hours = int(nonshift_hours)
            raise HTTPRedirect('shifts?id={}&message={}', attendee.id, 'Non-shift hours updated')

    @csrf_protected
    def update_notes(self, session, id, admin_notes, for_review=None):
        attendee = session.attendee(id)
        attendee.admin_notes = admin_notes
        if for_review is not None:
            attendee.for_review = for_review
        raise HTTPRedirect('shifts?id={}&message={}', id, 'Admin notes updated')

    @csrf_protected
    def assign(self, session, staffer_id, job_id):
        message = session.assign(staffer_id, job_id) or 'Shift added'
        raise HTTPRedirect('shifts?id={}&message={}', staffer_id, message)

    @csrf_protected
    def unassign(self, session, shift_id):
        shift = session.shift(shift_id)
        session.delete(shift)
        raise HTTPRedirect('shifts?id={}&message={}', shift.attendee.id, 'Staffer unassigned from shift')

    def feed(self, session, page='1', who='', what='', action=''):
        feed = session.query(Tracking).filter(Tracking.action != AUTO_BADGE_SHIFT).order_by(Tracking.when.desc())
        if who:
            feed = feed.filter_by(who=who)
        if what:
            like = '%' + what + '%'  # SQLAlchemy should have an icontains for this
            feed = feed.filter(or_(Tracking.data.ilike(like), Tracking.which.ilike(like)))
        if action:
            feed = feed.filter_by(action=action)
        return {
            'who': who,
            'what': what,
            'page': page,
            'action': action,
            'count': feed.count(),
            'feed': get_page(page, feed),
            'action_opts': [opt for opt in TRACKING_OPTS if opt[0] != AUTO_BADGE_SHIFT],
            'who_opts': [who for [who] in session.query(Tracking).distinct().order_by(Tracking.who).values(Tracking.who)]
        }

    def staffers(self, session, message='', order='first_name', search_text=''):
        jobs, shifts, staffers = session.everything()
        if search_text:
            staffers = session.search(search_text, Attendee.staffing == True).options(joinedload(Attendee.shifts)).all()
        return {
            'order': Order(order),
            'message': message,
            'search_text': search_text,
            'staffer_count': len(staffers),
            'total_hours': sum(j.weighted_hours * j.slots for j in jobs),
            'taken_hours': sum(s.job.weighted_hours for s in shifts),
            'staffers': sorted(staffers, reverse=order.startswith('-'), key=lambda s: getattr(s, order.lstrip('-')))
        }

    def review(self, session):
        return {'attendees': session.query(Attendee)
                                    .filter(Attendee.for_review != '')
                                    .order_by(Attendee.full_name).all()}

    def season_pass_tickets(self, session):
        events = defaultdict(list)
        for spt in session.query(SeasonPassTicket).all():
            events[spt.slug].append(spt.fk)
        for attending in events.values():
            attending.sort(key=lambda a: (a.first_name, a.last_name))
        return {'events': dict(events)}

    @site_mappable
    def discount(self, session, message='', **params):
        attendee = session.attendee(params)
        if 'first_name' in params:
            if not attendee.first_name or not attendee.last_name:
                message = 'First and Last Name are required'
            elif not attendee.overridden_price:
                message = 'Discounted Price is required'
            elif attendee.overridden_price > state.BADGE_PRICE:
                message = 'You cannot create a discounted badge that costs more than the regular price!'

            if not message:
                session.add(attendee)
                attendee.placeholder = True
                attendee.badge_type = ATTENDEE_BADGE
                raise HTTPRedirect('../preregistration/confirm?id={}', attendee.id)

        return {'message': message}

    def placeholders(self, session, department=''):
        return {
            'department': department,
            'dept_name': JOB_LOCATIONS[int(department)] if department else 'All',
            'checklist': session.checklist_status('placeholders', department),
            'placeholders': [a for a in session.query(Attendee)
                                               .filter(Attendee.placeholder == True,
                                                       Attendee.staffing == True,
                                                       Attendee.assigned_depts.contains(department))
                                               .order_by(Attendee.full_name).all()]
        }
