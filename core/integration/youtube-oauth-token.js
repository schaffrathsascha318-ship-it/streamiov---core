const https = require("https");
const querystring = require("querystring");

function exchangeAuthorizationCode(config, code) {
  return new Promise((resolve, reject) => {
    if (!config || !config.client_id || !config.client_secret || !config.redirect_uri) {
      return resolve({
        ok: false,
        status: "user_action_required",
        reason: "oauth_configuration_missing",
        production_verified: false
      });
    }

    if (!code) {
      return resolve({
        ok: false,
        status: "authorization_code_missing",
        production_verified: false
      });
    }

    const body = querystring.stringify({
      code,
      client_id: config.client_id,
      client_secret: config.client_secret,
      redirect_uri: config.redirect_uri,
      grant_type: "authorization_code"
    });

    const request = https.request({
      hostname: "oauth2.googleapis.com",
      path: "/token",
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": Buffer.byteLength(body)
      }
    }, response => {
      let data = "";

      response.on("data", chunk => {
        data += chunk;
      });

      response.on("end", () => {
        let parsed;

        try {
          parsed = JSON.parse(data);
        } catch (_) {
          return resolve({
            ok: false,
            status: "oauth_provider_invalid_response",
            http_status: response.statusCode,
            production_verified: false
          });
        }

        if (response.statusCode < 200 || response.statusCode >= 300) {
          return resolve({
            ok: false,
            status: "oauth_token_exchange_failed",
            http_status: response.statusCode,
            error: parsed.error || "token_exchange_failed",
            production_verified: false
          });
        }

        resolve({
          ok: true,
          status: "token_exchange_successful",
          token_type: parsed.token_type || null,
          expires_in: parsed.expires_in || null,
          scope: parsed.scope || null,
          refresh_token_present: Boolean(parsed.refresh_token),
          access_token_present: Boolean(parsed.access_token),
          production_verified: true
        });
      });
    });

    request.on("error", error => {
      resolve({
        ok: false,
        status: "oauth_provider_unreachable",
        error: error.message,
        production_verified: false
      });
    });

    request.write(body);
    request.end();
  });
}

module.exports = {
  exchangeAuthorizationCode
};
