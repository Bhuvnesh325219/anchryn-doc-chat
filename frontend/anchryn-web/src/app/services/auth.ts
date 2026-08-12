import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Observable, throwError } from 'rxjs';
import { catchError, tap } from 'rxjs/operators';

import { environment } from '../../environments/environment';
import { AuthResponse, UserProfile } from '../models/anchryn.models';

const TOKEN_KEY = 'anchryn.token';

/**
 * Sign-in state and the access token.
 *
 * The token lives in localStorage. That trades some XSS exposure for not
 * needing cross-site cookies and the CSRF machinery they bring — a reasonable
 * trade here because the app never builds HTML from untrusted input, so there
 * is no obvious injection route. A cookie-based session would be stronger and
 * is the thing to change if this ever handles genuinely sensitive documents.
 */
@Injectable({ providedIn: 'root' })
export class Auth {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);
  private readonly base = `${environment.apiBaseUrl}/api/auth`;

  private readonly _token = signal<string | null>(readStoredToken());
  private readonly _user = signal<UserProfile | null>(null);

  readonly user = this._user.asReadonly();
  readonly signedIn = computed(() => this._token() !== null);
  /** True until the stored token has been checked against the server. */
  readonly restoring = signal(readStoredToken() !== null);

  token(): string | null {
    return this._token();
  }

  /**
   * Confirm a stored token still works, on startup.
   *
   * Without this a token that expired while the tab was closed would let the UI
   * render as signed in, then fail every request.
   */
  restore(): void {
    if (!this._token()) {
      this.restoring.set(false);
      return;
    }

    this.http.get<UserProfile>(`${this.base}/me`).subscribe({
      next: (user) => {
        this._user.set(user);
        this.restoring.set(false);
      },
      error: () => {
        this.clear();
        this.restoring.set(false);
      },
    });
  }

  register(email: string, password: string): Observable<AuthResponse> {
    return this.http
      .post<AuthResponse>(`${this.base}/register`, { email, password })
      .pipe(tap((response) => this.accept(response)), catchError(toMessage));
  }

  login(email: string, password: string): Observable<AuthResponse> {
    return this.http
      .post<AuthResponse>(`${this.base}/login`, { email, password })
      .pipe(tap((response) => this.accept(response)), catchError(toMessage));
  }

  signOut(): void {
    this.clear();
    this.router.navigate(['/sign-in']);
  }

  /** Called by the interceptor when the server rejects the token mid-session. */
  clear(): void {
    this._token.set(null);
    this._user.set(null);
    localStorage.removeItem(TOKEN_KEY);
  }

  private accept(response: AuthResponse): void {
    this._token.set(response.access_token);
    this._user.set(response.user);
    localStorage.setItem(TOKEN_KEY, response.access_token);
    this.restoring.set(false);
  }
}

function readStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    // Private browsing modes can throw on access rather than returning null.
    return null;
  }
}

function toMessage(response: HttpErrorResponse) {
  const detail = (response.error as { detail?: unknown } | null)?.detail;

  if (typeof detail === 'string') {
    return throwError(() => new Error(detail));
  }
  if (Array.isArray(detail)) {
    // Pydantic validation errors: surface the field that failed.
    const first = detail[0] as { loc?: unknown[]; msg?: string } | undefined;
    const field = Array.isArray(first?.loc) ? first.loc[first.loc.length - 1] : '';
    return throwError(() => new Error(field ? `${field}: ${first?.msg}` : 'That input was rejected.'));
  }
  if (response.status === 0) {
    return throwError(() => new Error('Cannot reach the server. Is the backend running?'));
  }
  return throwError(() => new Error(`Request failed with status ${response.status}.`));
}
