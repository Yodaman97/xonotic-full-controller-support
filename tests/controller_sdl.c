/* Exercise the production SDL poller and shared movement/key-event path. */
#include "joy_sdl.h"
#ifndef CONTROLLER_SDL_ONLY
#include "quakedef.h"
#endif
#include <assert.h>
#include <stdio.h>

#ifndef CONTROLLER_SDL_ONLY
client_state_t cl;
host_static_t host;
cvar_t cl_forwardspeed, cl_sidespeed, cl_upspeed, cl_pitchspeed, cl_yawspeed;
extern cvar_t joy_x360_axisforward, joy_x360_axisside, joy_x360_axisup;
extern cvar_t joy_x360_axispitch, joy_x360_axisyaw;
extern cvar_t joy_x360_deadzoneforward, joy_x360_deadzoneside;
extern cvar_t joy_x360_deadzonepitch, joy_x360_deadzoneyaw;
extern cvar_t joy_x360_sensitivityforward, joy_x360_sensitivityside;
extern cvar_t joy_x360_sensitivitypitch, joy_x360_sensitivityyaw;
static int presses[MAX_KEYS], releases[MAX_KEYS];

void Key_Event(int key, int ascii, qbool down)
{
	(void)ascii;
	assert(key >= 0 && key < MAX_KEYS);
	if (down) ++presses[key]; else ++releases[key];
}

static void apply(const joy_sdl_state_t *state)
{
	vid_joystate_t engine;
	memset(&engine, 0, sizeof(engine));
	memcpy(engine.axis, state->axis, sizeof(engine.axis));
	memcpy(engine.button, state->button, sizeof(engine.button));
	engine.is360 = state->mapped;
	VID_Shared_BuildJoyState_Finish(&engine);
	VID_ApplyJoyState(&engine);
}
#endif

static int attach_controller(void)
{
	char guid[33], mapping[1024];
	int index = SDL_JoystickAttachVirtual(SDL_JOYSTICK_TYPE_GAMECONTROLLER, 6, 15, 0);
	assert(index >= 0);
	SDL_JoystickGetGUIDString(SDL_JoystickGetDeviceGUID(index), guid, sizeof(guid));
	SDL_snprintf(mapping, sizeof(mapping), "%s,Milestone Xbox virtual,a:b0,b:b1,x:b2,y:b3,back:b4,guide:b5,start:b6,leftstick:b7,rightstick:b8,leftshoulder:b9,rightshoulder:b10,dpup:b11,dpdown:b12,dpleft:b13,dpright:b14,leftx:a0,lefty:a1,rightx:a2,righty:a3,lefttrigger:a4,righttrigger:a5,", guid);
	assert(SDL_GameControllerAddMapping(mapping) >= 0);
	return index;
}

int main(int argc, char **argv)
{
	joy_sdl_device_t device = {NULL, NULL, -1};
	joy_sdl_state_t state;
	struct { joy_sdl_state_t state; unsigned int canary; } guarded;
	SDL_JoystickID previous;
	int index, raw, j;
	(void)argc;
	(void)argv;
	SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1");
	assert(SDL_Init(SDL_INIT_GAMECONTROLLER) == 0);
	assert(!JoySDL_Select(&device, -1));
	JoySDL_Poll(&device, &state, .5f);
	assert(!state.mapped && state.axis[0] == 0);
	puts("PASS no controller at startup");

	index = attach_controller();
	assert(JoySDL_Select(&device, index));
	assert(device.controller);
	assert(!JoySDL_Select(&device, index));
	for (j = 0; j < 6; ++j)
		assert(SDL_JoystickSetVirtualAxis(device.joystick, j, j >= 4 ? -32768 : 0) == 0);
	SDL_GameControllerUpdate();
	JoySDL_Poll(&device, &state, .5f);
	assert(state.mapped && !state.button[14] && !state.button[15]);
	puts("PASS startup/late connection and stable ownership");

	/* Every physical SDL button has exactly one stable logical key. */
	{
		const int logical[] = {10,11,12,13,5,-1,4,6,7,8,9,0,1,2,3};
		for (j = 0; j < 15; ++j)
		{
			int k, sum = 0;
			assert(SDL_JoystickSetVirtualButton(device.joystick, j, 1) == 0);
			SDL_GameControllerUpdate();
			JoySDL_Poll(&device, &state, .5f);
			for (k = 0; k < 24; ++k) sum += state.button[k];
			assert(sum == (logical[j] < 0 ? 0 : 1));
			if (logical[j] >= 0) assert(state.button[logical[j]]);
			assert(SDL_JoystickSetVirtualButton(device.joystick, j, 0) == 0);
		}
	}
	puts("PASS stable face/shoulder/dpad/start/back/stick mappings; guide ignored");

	assert(SDL_JoystickSetVirtualAxis(device.joystick, 4, 32767) == 0);
	SDL_GameControllerUpdate();
	JoySDL_Poll(&device, &state, .5f);
	assert(state.axis[4] == 1 && state.axis[5] == 0);
	assert(state.button[14] && !state.button[15]);
	assert(SDL_JoystickSetVirtualAxis(device.joystick, 5, 32767) == 0);
	SDL_GameControllerUpdate();
	JoySDL_Poll(&device, &state, .5f);
	assert(state.button[14] && state.button[15]);
	assert(SDL_JoystickSetVirtualAxis(device.joystick, 4, -32768) == 0);
	SDL_GameControllerUpdate();
	JoySDL_Poll(&device, &state, .5f);
	assert(!state.button[14] && state.button[15]);
	assert(SDL_JoystickSetVirtualAxis(device.joystick, 5, 0) == 0);
	SDL_GameControllerUpdate();
	JoySDL_Poll(&device, &state, .5f);
	assert(state.axis[5] > .49f && state.axis[5] < .51f && !state.button[15]);
	puts("PASS independent analog triggers and digital thresholds");

#ifndef CONTROLLER_SDL_ONLY
	joy_x360_axisforward.integer = 1; joy_x360_axisside.integer = 0;
	joy_x360_axisup.integer = -1;
	joy_x360_axispitch.integer = 3; joy_x360_axisyaw.integer = 2;
	joy_x360_sensitivityforward.value = joy_x360_sensitivityside.value = 1;
	joy_x360_sensitivitypitch.value = joy_x360_sensitivityyaw.value = -1;
	joy_x360_deadzoneforward.value = joy_x360_deadzoneside.value = .266f;
	joy_x360_deadzonepitch.value = joy_x360_deadzoneyaw.value = .266f;
	cl_forwardspeed.value = cl_sidespeed.value = cl_upspeed.value = 400;
	cl_pitchspeed.value = cl_yawspeed.value = 100;
	cl.realframetime = .01;
	assert(SDL_JoystickSetVirtualAxis(device.joystick, 0, 1000) == 0);
	SDL_GameControllerUpdate(); JoySDL_Poll(&device, &state, .5f);
	apply(&state);
	assert(cl.cmd.sidemove == 0); /* drift inside deadzone */
	assert(SDL_JoystickSetVirtualAxis(device.joystick, 0, 32767) == 0);
	assert(SDL_JoystickSetVirtualAxis(device.joystick, 1, -32768) == 0);
	assert(SDL_JoystickSetVirtualAxis(device.joystick, 2, 32767) == 0);
	assert(SDL_JoystickSetVirtualAxis(device.joystick, 3, -32768) == 0);
	assert(SDL_JoystickSetVirtualButton(device.joystick, 0, 1) == 0);
	SDL_GameControllerUpdate(); JoySDL_Poll(&device, &state, .5f);
	cl.cmd.forwardmove = 123; cl.viewangles[0] = 10;
	apply(&state);
	assert(cl.cmd.forwardmove > 522 && cl.cmd.sidemove > 399);
	assert(cl.viewangles[0] < 10 && cl.viewangles[1] < 0);
	assert(presses[K_X360_A] == 1);
	apply(&state);
	assert(presses[K_X360_A] == 1); /* no second backend/duplicate initial press */
	puts("PASS deadzones, movement/aim directions, additive keyboard/mouse state and one button press");
#endif

	previous = device.instance;
	assert(SDL_JoystickDetachVirtual(index) == 0);
	SDL_GameControllerUpdate();
	/* Removal can be processed after VID_EnableJoystick selected the device
	 * but before IN_Move polls it. A neutral state must keep the old layout. */
	JoySDL_Poll(&device, &state, .5f);
	assert(state.mapped && state.axis[0] == 0 && !state.button[10]);
#ifndef CONTROLLER_SDL_ONLY
	apply(&state);
	assert(releases[K_X360_A] == 1 && releases[K_JOY11] == 0);
#endif
	assert(JoySDL_Select(&device, index));
#ifndef CONTROLLER_SDL_ONLY
	VID_ReleaseJoyState();
	assert(releases[K_X360_A] == 1);
#endif
	assert(!device.joystick);
	index = attach_controller();
	assert(JoySDL_Select(&device, index));
	assert(device.instance != previous);
	assert(!JoySDL_Select(&device, index));
	assert(JoySDL_Select(&device, -1));
	assert(SDL_JoystickDetachVirtual(index) == 0);
	puts("PASS disconnect, reconnect at same index, disable");

	/* Oversized raw HID reports must not overwrite the fixed state arrays. */
	raw = SDL_JoystickAttachVirtual(SDL_JOYSTICK_TYPE_UNKNOWN, 24, 48, 0);
	assert(raw >= 0 && JoySDL_Select(&device, raw));
	assert(!device.controller);
	for (j = 0; j < 24; ++j) assert(SDL_JoystickSetVirtualAxis(device.joystick, j, -32768) == 0);
	for (j = 0; j < 48; ++j) assert(SDL_JoystickSetVirtualButton(device.joystick, j, 1) == 0);
	SDL_JoystickUpdate();
	guarded.canary = 0x12345678;
	JoySDL_Poll(&device, &guarded.state, .5f);
	assert(guarded.canary == 0x12345678 && !guarded.state.mapped);
	assert(guarded.state.axis[15] == -1 && guarded.state.button[35]);
	JoySDL_Close(&device);
	assert(SDL_JoystickDetachVirtual(raw) == 0);
	SDL_Quit();
	puts("PASS oversized raw reports bounded; all controller checks passed");
	return 0;
}
