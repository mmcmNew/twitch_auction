from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app

client = TestClient(app)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _bootstrap_users_and_roles():
    client.post('/users', json={'login': 'alice', 'display_name': 'Alice'})
    client.post('/users', json={'login': 'bob', 'display_name': 'Bob'})
    client.post('/users', json={'login': 'charlie', 'display_name': 'Charlie'})

    client.post('/memberships', json={'channel_login': 'alice', 'user_login': 'alice', 'role': 'streamer'})
    client.post('/memberships', json={'channel_login': 'alice', 'user_login': 'bob', 'role': 'moderator'})
    client.post('/memberships', json={'channel_login': 'bob', 'user_login': 'bob', 'role': 'streamer'})
    client.post('/memberships', json={'channel_login': 'bob', 'user_login': 'alice', 'role': 'viewer'})


def test_healthcheck():
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}


def test_roles_are_channel_scoped_and_switchable():
    _bootstrap_users_and_roles()

    assert client.post(
        '/auctions',
        json={'title': 'Alice stream poll', 'channel_login': 'alice'},
        headers={'X-User-Login': 'alice'},
    ).status_code == 201

    assert client.post(
        '/auctions',
        json={'title': 'Bob stream poll', 'channel_login': 'bob'},
        headers={'X-User-Login': 'bob'},
    ).status_code == 201

    assert client.post(
        '/auctions',
        json={'title': 'No rights', 'channel_login': 'alice'},
        headers={'X-User-Login': 'charlie'},
    ).status_code == 403


def test_start_creates_rewards_from_streamer_settings():
    _bootstrap_users_and_roles()

    preset_response = client.put(
        '/channels/alice/reward-presets',
        json={'amounts': [5000, 25000]},
        headers={'X-User-Login': 'alice'},
    )
    assert preset_response.status_code == 200

    auction_id = client.post(
        '/auctions',
        json={'title': 'Configured rewards', 'channel_login': 'alice'},
        headers={'X-User-Login': 'alice'},
    ).json()['id']

    start_response = client.post(f'/auctions/{auction_id}/start', headers={'X-User-Login': 'alice'})
    assert start_response.status_code == 200
    assert start_response.json()['status'] == 'active'

    rewards_response = client.get(f'/auctions/{auction_id}/rewards')
    assert [reward['amount'] for reward in rewards_response.json()] == [5000, 25000]


def test_moderator_can_moderate_and_vote_with_own_balance():
    _bootstrap_users_and_roles()

    auction_id = client.post(
        '/auctions',
        json={'title': 'Weekend stream poll', 'channel_login': 'alice'},
        headers={'X-User-Login': 'alice'},
    ).json()['id']

    client.post(f'/auctions/{auction_id}/start', headers={'X-User-Login': 'alice'})

    suggestion_id = client.post(
        f'/auctions/{auction_id}/suggestions',
        json={'author': 'viewer_1', 'title': 'Portal 2'},
    ).json()['id']

    approve_response = client.post(f'/suggestions/{suggestion_id}/approve', headers={'X-User-Login': 'bob'})
    assert approve_response.status_code == 200

    position_id = client.get(f'/auctions/{auction_id}/positions').json()[0]['id']
    client.post(f'/auctions/{auction_id}/wallet/topup', json={'viewer': 'bob', 'amount': 500})

    contribution_response = client.post(
        f'/auctions/{auction_id}/contributions',
        json={'viewer': 'bob', 'position_id': position_id, 'amount': 200},
    )
    assert contribution_response.status_code == 201
    assert contribution_response.json()['base_amount'] == 200
    assert contribution_response.json()['multiplier'] == 1.0
    assert contribution_response.json()['amount'] == 200


def test_contribution_fails_when_balance_insufficient():
    _bootstrap_users_and_roles()

    auction_id = client.post(
        '/auctions',
        json={'title': 'Late night poll', 'channel_login': 'alice'},
        headers={'X-User-Login': 'alice'},
    ).json()['id']

    client.post(f'/auctions/{auction_id}/start', headers={'X-User-Login': 'alice'})
    position_id = client.post(
        f'/auctions/{auction_id}/positions',
        json={'title': 'Celeste'},
        headers={'X-User-Login': 'bob'},
    ).json()['id']

    client.post(f'/auctions/{auction_id}/wallet/topup', json={'viewer': 'charlie', 'amount': 100})
    failed = client.post(
        f'/auctions/{auction_id}/contributions',
        json={'viewer': 'charlie', 'position_id': position_id, 'amount': 150},
    )
    assert failed.status_code == 409


def test_lock_roulette_finish_closes_auction_and_sets_winner():
    _bootstrap_users_and_roles()
    auction_id = client.post(
        '/auctions',
        json={'title': 'Final with roulette', 'channel_login': 'alice'},
        headers={'X-User-Login': 'alice'},
    ).json()['id']

    client.post(f'/auctions/{auction_id}/start', headers={'X-User-Login': 'alice'})
    p1 = client.post(
        f'/auctions/{auction_id}/positions',
        json={'title': 'A'},
        headers={'X-User-Login': 'alice'},
    ).json()['id']

    client.post(f'/auctions/{auction_id}/lock', headers={'X-User-Login': 'alice'})

    blocked = client.post(
        f'/auctions/{auction_id}/contributions',
        json={'viewer': 'charlie', 'position_id': p1, 'amount': 10},
    )
    assert blocked.status_code == 409

    run = client.post(f'/auctions/{auction_id}/roulette/start', headers={'X-User-Login': 'alice'})
    assert run.status_code == 201
    assert run.json()['status'] == 'running'

    finish = client.post(
        f'/auctions/{auction_id}/roulette/finish',
        headers={'X-User-Login': 'alice'},
        json={'winner_position_id': p1},
    )
    assert finish.status_code == 200
    assert finish.json()['status'] == 'finished'

    auction = client.get(f'/auctions/{auction_id}')
    assert auction.json()['status'] == 'closed'
    assert auction.json()['winner_position_id'] == p1


def test_spin_contribution_applies_multiplier():
    _bootstrap_users_and_roles()

    auction_id = client.post(
        '/auctions',
        json={'title': 'Spin contribution', 'channel_login': 'alice'},
        headers={'X-User-Login': 'alice'},
    ).json()['id']
    client.post(f'/auctions/{auction_id}/start', headers={'X-User-Login': 'alice'})
    position_id = client.post(
        f'/auctions/{auction_id}/positions',
        json={'title': 'Game X'},
        headers={'X-User-Login': 'alice'},
    ).json()['id']
    client.post(f'/auctions/{auction_id}/wallet/topup', json={'viewer': 'charlie', 'amount': 500})

    spin = client.post(
        f'/auctions/{auction_id}/contributions/spin',
        json={
            'viewer': 'charlie',
            'position_id': position_id,
            'amount': 100,
            'multipliers': [2.0],
        },
    )
    assert spin.status_code == 201
    assert spin.json()['base_amount'] == 100
    assert spin.json()['multiplier'] == 2.0
    assert spin.json()['amount'] == 200


def test_closed_auction_history_uses_selected_winner():
    _bootstrap_users_and_roles()
    auction_id = client.post(
        '/auctions',
        json={'title': 'History with winner', 'channel_login': 'alice'},
        headers={'X-User-Login': 'alice'},
    ).json()['id']
    client.post(f'/auctions/{auction_id}/start', headers={'X-User-Login': 'alice'})
    p1 = client.post(
        f'/auctions/{auction_id}/positions',
        json={'title': 'Movie A'},
        headers={'X-User-Login': 'alice'},
    ).json()['id']
    p2 = client.post(
        f'/auctions/{auction_id}/positions',
        json={'title': 'Movie B'},
        headers={'X-User-Login': 'alice'},
    ).json()['id']

    client.post(f'/auctions/{auction_id}/lock', headers={'X-User-Login': 'alice'})
    client.post(f'/auctions/{auction_id}/roulette/start', headers={'X-User-Login': 'alice'})
    client.post(
        f'/auctions/{auction_id}/roulette/finish',
        headers={'X-User-Login': 'alice'},
        json={'winner_position_id': p2},
    )

    history = client.get('/history/auctions').json()[0]
    assert history['winner_title'] == 'Movie B'
    detail = client.get(f'/history/auctions/{auction_id}').json()
    assert detail['winner_title'] == 'Movie B'


def test_suggestion_rate_limit_per_auction_author():
    _bootstrap_users_and_roles()
    auction_id = client.post(
        '/auctions',
        json={'title': 'Rate limit', 'channel_login': 'alice'},
        headers={'X-User-Login': 'alice'},
    ).json()['id']

    for i in range(3):
        response = client.post(
            f'/auctions/{auction_id}/suggestions',
            json={'author': 'charlie', 'title': f'Idea {i}'},
        )
        assert response.status_code == 201

    blocked = client.post(
        f'/auctions/{auction_id}/suggestions',
        json={'author': 'charlie', 'title': 'Idea blocked'},
    )
    assert blocked.status_code == 429


def test_audit_log_contains_moderation_and_roulette_actions():
    _bootstrap_users_and_roles()
    auction_id = client.post(
        '/auctions',
        json={'title': 'Audit trail', 'channel_login': 'alice'},
        headers={'X-User-Login': 'alice'},
    ).json()['id']
    client.post(f'/auctions/{auction_id}/start', headers={'X-User-Login': 'alice'})

    suggestion_id = client.post(
        f'/auctions/{auction_id}/suggestions',
        json={'author': 'charlie', 'title': 'Entry'},
    ).json()['id']
    client.post(f'/suggestions/{suggestion_id}/approve', headers={'X-User-Login': 'bob'})

    position_id = client.get(f'/auctions/{auction_id}/positions').json()[0]['id']
    client.post(f'/auctions/{auction_id}/lock', headers={'X-User-Login': 'alice'})
    client.post(f'/auctions/{auction_id}/roulette/start', headers={'X-User-Login': 'alice'})
    client.post(
        f'/auctions/{auction_id}/roulette/finish',
        headers={'X-User-Login': 'alice'},
        json={'winner_position_id': position_id},
    )

    log = client.get('/audit-log', params={'auction_id': auction_id})
    assert log.status_code == 200
    actions = [row['action'] for row in log.json()]
    assert 'suggestion.approve' in actions
    assert 'auction.lock' in actions
    assert 'roulette.finish' in actions


def test_clone_auction_with_and_without_scores():
    _bootstrap_users_and_roles()
    source_id = client.post(
        '/auctions',
        json={'title': 'Long run', 'channel_login': 'alice'},
        headers={'X-User-Login': 'alice'},
    ).json()['id']
    client.post(f'/auctions/{source_id}/start', headers={'X-User-Login': 'alice'})
    p1 = client.post(
        f'/auctions/{source_id}/positions',
        json={'title': 'Film A'},
        headers={'X-User-Login': 'alice'},
    ).json()['id']
    p2 = client.post(
        f'/auctions/{source_id}/positions',
        json={'title': 'Film B'},
        headers={'X-User-Login': 'alice'},
    ).json()['id']

    client.post(f'/auctions/{source_id}/wallet/topup', json={'viewer': 'charlie', 'amount': 1000})
    client.post(f'/auctions/{source_id}/contributions', json={'viewer': 'charlie', 'position_id': p1, 'amount': 700})
    client.post(f'/auctions/{source_id}/contributions', json={'viewer': 'charlie', 'position_id': p2, 'amount': 300})

    clone_full = client.post(
        f'/auctions/{source_id}/clone',
        headers={'X-User-Login': 'alice'},
        json={'title': 'Long run next', 'carry_scores': True},
    )
    assert clone_full.status_code == 201
    clone_id = clone_full.json()['id']
    assert clone_full.json()['source_auction_id'] == source_id

    cloned_positions = client.get(f'/auctions/{clone_id}/positions').json()
    assert [p['points'] for p in cloned_positions] == [700, 300]

    clone_reset = client.post(
        f'/auctions/{source_id}/clone',
        headers={'X-User-Login': 'alice'},
        json={'carry_scores': True, 'reset_position_titles': ['Film A']},
    )
    assert clone_reset.status_code == 201
    reset_positions = client.get(f"/auctions/{clone_reset.json()['id']}/positions").json()
    assert reset_positions[0]['title'] == 'Film B'
    assert reset_positions[0]['points'] == 300
    assert reset_positions[1]['title'] == 'Film A'
    assert reset_positions[1]['points'] == 0


def test_ui_context_contains_stream_player_url_and_timer():
    _bootstrap_users_and_roles()
    auction_id = client.post(
        '/auctions',
        json={'title': 'Timed auction', 'channel_login': 'alice', 'duration_minutes': 30},
        headers={'X-User-Login': 'alice'},
    ).json()['id']
    client.post(f'/auctions/{auction_id}/start', headers={'X-User-Login': 'alice'})

    context = client.get(f'/auctions/{auction_id}/ui-context')
    assert context.status_code == 200
    payload = context.json()
    assert 'player.twitch.tv' in payload['stream_embed_url']
    assert payload['seconds_to_end'] is not None


def test_activity_feed_returns_recent_actions_for_ui():
    _bootstrap_users_and_roles()
    auction_id = client.post(
        '/auctions',
        json={'title': 'Activity feed', 'channel_login': 'alice'},
        headers={'X-User-Login': 'alice'},
    ).json()['id']
    client.post(f'/auctions/{auction_id}/start', headers={'X-User-Login': 'alice'})

    position_id = client.post(
        f'/auctions/{auction_id}/positions',
        json={'title': 'Lot 1'},
        headers={'X-User-Login': 'alice'},
    ).json()['id']

    client.post(f'/auctions/{auction_id}/wallet/topup', json={'viewer': 'charlie', 'amount': 500})
    client.post(
        f'/auctions/{auction_id}/contributions',
        json={'viewer': 'charlie', 'position_id': position_id, 'amount': 150},
    )

    feed = client.get(f'/auctions/{auction_id}/activity')
    assert feed.status_code == 200
    event_types = [item['type'] for item in feed.json()]
    assert 'wallet.topup' in event_types
    assert 'contribution.create' in event_types


def test_effects_endpoint_reports_recent_ui_signals():
    _bootstrap_users_and_roles()
    auction_id = client.post(
        '/auctions',
        json={'title': 'Effects', 'channel_login': 'alice', 'duration_minutes': 1},
        headers={'X-User-Login': 'alice'},
    ).json()['id']
    client.post(f'/auctions/{auction_id}/start', headers={'X-User-Login': 'alice'})

    position_id = client.post(
        f'/auctions/{auction_id}/positions',
        json={'title': 'Lot 1'},
        headers={'X-User-Login': 'alice'},
    ).json()['id']

    client.post(
        f'/auctions/{auction_id}/suggestions',
        json={'author': 'charlie', 'title': 'Suggestion X'},
    )
    client.post(f'/auctions/{auction_id}/wallet/topup', json={'viewer': 'charlie', 'amount': 5000})
    client.post(
        f'/auctions/{auction_id}/contributions',
        json={'viewer': 'charlie', 'position_id': position_id, 'amount': 1200},
    )

    effects = client.get(f'/auctions/{auction_id}/effects')
    assert effects.status_code == 200
    payload = effects.json()
    assert payload['leader_changed'] is True
    assert payload['large_contribution'] is True
    assert payload['auction_ending_soon'] is True
    assert payload['new_vote_or_suggestion'] is True


def test_events_endpoint_exposes_sse_stream():
    _bootstrap_users_and_roles()
    auction_id = client.post(
        '/auctions',
        json={'title': 'Realtime feed', 'channel_login': 'alice'},
        headers={'X-User-Login': 'alice'},
    ).json()['id']
    client.post(f'/auctions/{auction_id}/start', headers={'X-User-Login': 'alice'})

    with client.stream('GET', f'/auctions/{auction_id}/events') as response:
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('text/event-stream')
        first_chunk = next(response.iter_text())
        assert 'event: snapshot' in first_chunk
        assert '"auction_id":' in first_chunk


def test_restart_closed_auction_with_auto_start():
    _bootstrap_users_and_roles()
    source_id = client.post(
        '/auctions',
        json={'title': 'Season finale', 'channel_login': 'alice', 'duration_minutes': 15},
        headers={'X-User-Login': 'alice'},
    ).json()['id']

    client.post(f'/auctions/{source_id}/start', headers={'X-User-Login': 'alice'})
    p1 = client.post(
        f'/auctions/{source_id}/positions',
        json={'title': 'Game 1'},
        headers={'X-User-Login': 'alice'},
    ).json()['id']
    client.post(f'/auctions/{source_id}/wallet/topup', json={'viewer': 'charlie', 'amount': 500})
    client.post(
        f'/auctions/{source_id}/contributions',
        json={'viewer': 'charlie', 'position_id': p1, 'amount': 200},
    )
    client.post(f'/auctions/{source_id}/lock', headers={'X-User-Login': 'alice'})
    client.post(f'/auctions/{source_id}/roulette/start', headers={'X-User-Login': 'alice'})
    client.post(
        f'/auctions/{source_id}/roulette/finish',
        headers={'X-User-Login': 'alice'},
        json={'winner_position_id': p1},
    )

    restarted = client.post(
        f'/auctions/{source_id}/restart',
        headers={'X-User-Login': 'alice'},
        json={'carry_scores': False, 'auto_start': True},
    )
    assert restarted.status_code == 201
    payload = restarted.json()
    assert payload['source_auction_id'] == source_id
    assert payload['status'] == 'active'
    assert payload['ends_at'] is not None

    positions = client.get(f"/auctions/{payload['id']}/positions").json()
    assert positions[0]['points'] == 0


def test_restart_requires_closed_source():
    _bootstrap_users_and_roles()
    source_id = client.post(
        '/auctions',
        json={'title': 'Not closed yet', 'channel_login': 'alice'},
        headers={'X-User-Login': 'alice'},
    ).json()['id']

    response = client.post(
        f'/auctions/{source_id}/restart',
        headers={'X-User-Login': 'alice'},
        json={'carry_scores': True},
    )
    assert response.status_code == 409
    assert response.json()['detail'] == 'Only closed auction can be restarted'


def test_error_response_format_for_missing_resource():
    _bootstrap_users_and_roles()
    response = client.get('/auctions/999999')
    assert response.status_code == 404
    payload = response.json()
    assert payload['code'] == 'http_404'
    assert payload['message'] == 'Auction not found'


def test_validation_error_response_format():
    _bootstrap_users_and_roles()
    response = client.post(
        '/auctions',
        json={'title': '', 'channel_login': 'alice'},
        headers={'X-User-Login': 'alice'},
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload['code'] == 'validation_error'
    assert payload['message'] == 'Request validation failed'
    assert isinstance(payload['details'], list)


def test_list_auctions_supports_channel_and_status_filters():
    _bootstrap_users_and_roles()

    a1 = client.post(
        '/auctions',
        json={'title': 'Alice open', 'channel_login': 'alice'},
        headers={'X-User-Login': 'alice'},
    ).json()['id']
    client.post(f'/auctions/{a1}/start', headers={'X-User-Login': 'alice'})

    a2 = client.post(
        '/auctions',
        json={'title': 'Bob draft', 'channel_login': 'bob'},
        headers={'X-User-Login': 'bob'},
    ).json()['id']
    assert a2 > 0

    filtered = client.get('/auctions', params={'channel_login': 'alice', 'status_filter': 'active'})
    assert filtered.status_code == 200
    assert len(filtered.json()) == 1
    assert filtered.json()[0]['channel_login'] == 'alice'
    assert filtered.json()[0]['status'] == 'active'


def test_history_supports_channel_filter_and_limit():
    _bootstrap_users_and_roles()

    for idx in range(2):
        auction_id = client.post(
            '/auctions',
            json={'title': f'Alice closed {idx}', 'channel_login': 'alice'},
            headers={'X-User-Login': 'alice'},
        ).json()['id']
        client.post(f'/auctions/{auction_id}/start', headers={'X-User-Login': 'alice'})
        position_id = client.post(
            f'/auctions/{auction_id}/positions',
            json={'title': f'Lot {idx}'},
            headers={'X-User-Login': 'alice'},
        ).json()['id']
        client.post(f'/auctions/{auction_id}/lock', headers={'X-User-Login': 'alice'})
        client.post(f'/auctions/{auction_id}/roulette/start', headers={'X-User-Login': 'alice'})
        client.post(
            f'/auctions/{auction_id}/roulette/finish',
            headers={'X-User-Login': 'alice'},
            json={'winner_position_id': position_id},
        )

    response = client.get('/history/auctions', params={'channel_login': 'alice', 'limit': 1})
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]['channel_login'] == 'alice'


def test_email_auth_register_login_and_bearer_access_for_protected_endpoint():
    register = client.post(
        '/auth/register',
        json={
            'email': 'alice@example.com',
            'password': 'secret123',
            'display_name': 'Alice',
            'login': 'alice',
        },
    )
    assert register.status_code == 201
    register_payload = register.json()
    assert register_payload['token_type'] == 'bearer'
    assert register_payload['user_login'] == 'alice'

    client.post('/memberships', json={'channel_login': 'alice', 'user_login': 'alice', 'role': 'streamer'})

    login = client.post('/auth/login', json={'email': 'alice@example.com', 'password': 'secret123'})
    assert login.status_code == 200
    token = login.json()['access_token']

    response = client.post(
        '/auctions',
        json={'title': 'Email auth auction', 'channel_login': 'alice'},
        headers={'Authorization': f'Bearer {token}'},
    )
    assert response.status_code == 201
    assert response.json()['channel_login'] == 'alice'


def test_email_auth_login_fails_with_wrong_password():
    client.post(
        '/auth/register',
        json={
            'email': 'viewer@example.com',
            'password': 'correctpass',
            'display_name': 'Viewer',
            'login': 'viewer',
        },
    )

    login = client.post('/auth/login', json={'email': 'viewer@example.com', 'password': 'wrongpass'})
    assert login.status_code == 401
    assert login.json()['message'] == 'Invalid email or password'
