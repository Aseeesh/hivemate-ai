import { CognitoUserPool, CognitoUser, CognitoUserAttribute, AuthenticationDetails } from 'amazon-cognito-identity-js';

const pool = () => new CognitoUserPool({
  UserPoolId: process.env.NEXT_PUBLIC_USER_POOL_ID!,
  ClientId: process.env.NEXT_PUBLIC_USER_POOL_CLIENT_ID!,
});
const user = (email: string) => new CognitoUser({ Username: email, Pool: pool() });

export function signUp(email: string, password: string, businessName: string) {
  const attrs = [
    new CognitoUserAttribute({ Name: 'email', Value: email }),
    new CognitoUserAttribute({ Name: 'custom:businessName', Value: businessName }),
  ];
  return new Promise<void>((res, rej) => pool().signUp(email, password, attrs, [], (e) => (e ? rej(e) : res())));
}

export function confirm(email: string, code: string) {
  return new Promise<void>((res, rej) => user(email).confirmRegistration(code, true, (e) => (e ? rej(e) : res())));
}

export function signIn(email: string, password: string) {
  return new Promise<void>((res, rej) =>
    user(email).authenticateUser(new AuthenticationDetails({ Username: email, Password: password }), {
      onSuccess: () => res(),
      onFailure: rej,
    }));
}

export function signOut() { pool().getCurrentUser()?.signOut(); }

/** Current ID token; amazon-cognito-identity-js refreshes it from the refresh token when expired. */
export function idToken(): Promise<string | null> {
  const u = pool().getCurrentUser();
  if (!u) return Promise.resolve(null);
  return new Promise((res) => u.getSession((e: Error | null, s: { getIdToken(): { getJwtToken(): string } } | null) => res(e || !s ? null : s.getIdToken().getJwtToken())));
}
