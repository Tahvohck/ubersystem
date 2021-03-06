from uber.tests import *

# TODO: I'm using some MAGFest-specific values, but this will fail if e.g. someone eliminates ARCADE as a department

def test_ints():
    assert [] == Attendee().interests_ints
    assert [ARCADE] == Attendee(interests=ARCADE).interests_ints
    assert [ARCADE, CONSOLE] == Attendee(interests='{},{}'.format(ARCADE, CONSOLE)).interests_ints

def test_label():
    assert '' == Attendee(paid=None).paid_label
    assert 'yes' == Attendee(paid=HAS_PAID).paid_label

def test_local():
    utcnow = datetime.now(UTC)
    assert UTC == Attendee(registered=utcnow).registered.tzinfo
    assert EVENT_TIMEZONE.zone == Attendee(registered=utcnow).registered_local.tzinfo.zone

def test_multi_checks():
    pytest.raises(AttributeError, lambda: Attendee().CONSOLE)
    pytest.raises(AttributeError, lambda: HotelRequests().CONSOLE)
    pytest.raises(AttributeError, lambda: Attendee().NOT_A_REAL_CHOICE)

    assert not HotelRequests().THURSDAY
    assert HotelRequests(nights='{},{}'.format(FRIDAY, SATURDAY)).FRIDAY
    assert not HotelRequests(nights='{},{}'.format(FRIDAY, SATURDAY)).SUNDAY
