import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from scripts import update_data as u


class RequestTests(unittest.TestCase):
    def setUp(self):
        u._blocked_hosts.clear()
        u._last_request.clear()

    def test_denial_stops_host_without_retry(self):
        for status in (403, 429):
            with self.subTest(status=status):
                u._blocked_hosts.clear()
                response = Mock(status_code=status, headers={'Retry-After': '600'})
                with patch.object(u.requests, 'get', return_value=response) as get:
                    with self.assertRaises(u.requests.HTTPError):
                        u.request('https://api.syosetu.com/novelapi/api/')
                    with self.assertRaises(RuntimeError):
                        u.request('https://api.syosetu.com/rank/rankget/')
                    self.assertEqual(get.call_count, 1)
                    self.assertEqual(get.call_args.kwargs['headers'], u.HEADERS)

    def test_requests_are_spaced(self):
        response = Mock(status_code=200)
        u._last_request['api.syosetu.com'] = 100
        with patch.object(u.time, 'monotonic', return_value=101), patch.object(u.time, 'sleep') as sleep, patch.object(u.requests, 'get', return_value=response):
            u.request('https://api.syosetu.com/novelapi/api/')
            sleep.assert_called_once_with(2)

    def test_kasasagi_never_accessed(self):
        with patch.object(u.requests, 'get') as get:
            with self.assertRaisesRegex(RuntimeError, 'disabled'):
                u.parse_kasasagi('n1234ab')
            get.assert_not_called()


class PublicationTests(unittest.TestCase):
    def test_failed_run_preserves_all_files(self):
        for mode in ('api', 'all', 'partial', 'missing_api_row'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                previous = os.getcwd()
                try:
                    os.chdir(directory)
                    Path('scripts').mkdir()
                    Path('config.json').write_text(json.dumps({'books': [
                        {'ncode': 'one', 'kakuyomuId': '1'},
                        {'ncode': 'two', 'kakuyomuId': '2'},
                    ]}))
                    paths = ['data.js', u.CACHE_PATH, u.DAILY_CACHE_PATH, u.KAKUYOMU_STATS_CACHE_PATH, u.KAKUYOMU_DAILY_CACHE_PATH, u.STATS_HISTORY_PATH, u.RANKINGS_AUTO_PATH]
                    for path in paths:
                        Path(path).write_text('existing dashboard' if path == 'data.js' else '{}')
                    before = {path: Path(path).read_bytes() for path in paths}
                    api = Mock(side_effect=RuntimeError('403')) if mode == 'api' else Mock(return_value={} if mode == 'missing_api_row' else {'one': {}, 'two': {}})
                    kasasagi = Mock(side_effect=RuntimeError('403')) if mode == 'all' else Mock(return_value={'periodStart': ''})
                    if mode == 'partial':
                        kasasagi = Mock(side_effect=[{'periodStart': ''}, RuntimeError('403')])
                    with patch.object(u, 'fetch_narou_api_stats', api), patch.object(u, 'check_and_record_rankings'), patch.object(u, 'parse_kasasagi', kasasagi), patch.object(u, 'build_naro_episode_cumulative', return_value=[]), patch.object(u, 'build_naro_daily_history', return_value=[]), patch.object(u, 'parse_kakuyomu', return_value={'totalPv': 10}), patch.object(u, 'get_kakuyomu_work_stats_cached', return_value={}), patch.object(u, 'render_book', return_value='book'), patch.object(u.time, 'sleep'):
                        with self.assertRaises(RuntimeError):
                            u.main()
                    self.assertEqual(before, {path: Path(path).read_bytes() for path in paths})
                finally:
                    os.chdir(previous)

    def test_successful_prerelease_only_run(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = os.getcwd()
            try:
                os.chdir(directory)
                Path('scripts').mkdir()
                book = dict(ncode='future', kakuyomuId='1', title='Future', shortTitle='F', mood='', prerelease=True, releaseDate='2099-01-01')
                Path('config.json').write_text(json.dumps({'books': [book]}))
                with patch.object(u, 'check_and_record_rankings'), patch.object(u.requests, 'get') as get:
                    u.main()
                    get.assert_not_called()
                self.assertIn('future', Path('data.js').read_text(encoding='utf-8'))
                self.assertFalse(Path('data.js.tmp').exists())
            finally:
                os.chdir(previous)


if __name__ == '__main__':
    unittest.main()
