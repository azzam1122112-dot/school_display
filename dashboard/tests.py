from django.test import Client, TestCase


class DashboardLoginCsrfTests(TestCase):
	def setUp(self):
		self.client = Client(enforce_csrf_checks=True)

	def test_login_get_sets_csrf_cookie_and_no_store_headers(self):
		response = self.client.get("/dashboard/login/")

		self.assertEqual(response.status_code, 200)
		self.assertIn("csrftoken", response.cookies)
		self.assertContains(response, "csrfmiddlewaretoken")

		cache_control = (response.get("Cache-Control") or "").lower()
		self.assertIn("no-store", cache_control)
		self.assertIn("no-cache", cache_control)

	def test_login_post_with_valid_csrf_token_does_not_403(self):
		get_response = self.client.get("/dashboard/login/")
		csrf_token = get_response.cookies["csrftoken"].value

		response = self.client.post(
			"/dashboard/login/",
			{
				"username": "missing-user",
				"password": "bad-password",
				"csrfmiddlewaretoken": csrf_token,
			},
			HTTP_REFERER="http://testserver/dashboard/login/",
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "بيانات الدخول غير صحيحة")

	def test_login_csrf_failure_renders_login_with_fresh_token(self):
		response = self.client.post(
			"/dashboard/login/",
			{
				"username": "missing-user",
				"password": "bad-password",
				"csrfmiddlewaretoken": "stale-token",
			},
			HTTP_REFERER="http://testserver/dashboard/login/",
		)

		self.assertEqual(response.status_code, 403)
		self.assertContains(response, "انتهت صلاحية جلسة الحماية", status_code=403)
		self.assertContains(response, "csrfmiddlewaretoken", status_code=403)
		cache_control = (response.get("Cache-Control") or "").lower()
		self.assertIn("no-store", cache_control)
