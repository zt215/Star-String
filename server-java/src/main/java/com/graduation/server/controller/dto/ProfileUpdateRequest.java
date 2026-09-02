package com.graduation.server.controller.dto;

public record ProfileUpdateRequest(
        String username,
        String nickname,
        String phone,
        String email
) {
}
