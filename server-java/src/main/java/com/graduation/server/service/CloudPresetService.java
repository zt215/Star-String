package com.graduation.server.service;

import com.graduation.server.controller.dto.CloudPresetResponse;
import com.graduation.server.entity.CloudPreset;
import com.graduation.server.repository.CloudPresetRepository;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class CloudPresetService {

    private final CloudPresetRepository repository;

    public CloudPresetService(CloudPresetRepository repository) {
        this.repository = repository;
    }

    public CloudPresetResponse save(String owner, String kind, String name, String content) {
        if (owner == null || owner.isBlank()) {
            throw new IllegalArgumentException("账号不能为空");
        }
        if (kind == null || !List.of("param", "system", "config").contains(kind)) {
            throw new IllegalArgumentException("不支持的方案类型");
        }
        if (name == null || name.isBlank()) {
            throw new IllegalArgumentException("方案名称不能为空");
        }
        if (content == null || content.isBlank()) {
            throw new IllegalArgumentException("方案内容不能为空");
        }
        String safeOwner = owner.trim().replaceAll("[^a-zA-Z0-9_\\-\\u4e00-\\u9fa5]", "_");
        CloudPreset preset = new CloudPreset(safeOwner, kind, name.trim(), content);
        repository.save(preset);
        return toResponse(preset);
    }

    public List<CloudPresetResponse> list(String owner, String kind) {
        String safeOwner = (owner == null || owner.isBlank()) ? "default" : owner.trim()
                .replaceAll("[^a-zA-Z0-9_\\-\\u4e00-\\u9fa5]", "_");
        if (kind == null || kind.isBlank() || !List.of("param", "system", "config").contains(kind)) {
            kind = "config";
        }
        return repository.findByOwnerAndKindOrderByCreatedAtDesc(safeOwner, kind).stream()
                .map(this::toResponse)
                .toList();
    }

    public void delete(String owner, Long id) {
        String safeOwner = (owner == null || owner.isBlank()) ? "default" : owner.trim()
                .replaceAll("[^a-zA-Z0-9_\\-\\u4e00-\\u9fa5]", "_");
        CloudPreset preset = repository.findByIdAndOwner(id, safeOwner)
                .orElseThrow(() -> new IllegalArgumentException("云方案不存在"));
        repository.delete(preset);
    }

    private CloudPresetResponse toResponse(CloudPreset preset) {
        return new CloudPresetResponse(
                preset.getId(),
                preset.getOwner(),
                preset.getKind(),
                preset.getName(),
                preset.getContent(),
                preset.getCreatedAt().toString()
        );
    }
}
