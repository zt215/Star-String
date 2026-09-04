package com.graduation.server.service;

import com.graduation.server.controller.dto.CloudModelResponse;
import com.graduation.server.entity.CloudModel;
import com.graduation.server.repository.CloudModelRepository;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;
import java.util.UUID;

@Service
public class CloudModelService {

    private final CloudModelRepository repository;
    private final Path uploadRoot;

    public CloudModelService(
            CloudModelRepository repository,
            @Value("${app.upload-dir:./uploads/cloud}") String uploadDir
    ) {
        this.repository = repository;
        this.uploadRoot = Paths.get(uploadDir).toAbsolutePath().normalize();
    }

    public CloudModelResponse upload(String owner, String kind, String name, MultipartFile file) throws IOException {
        if (file == null || file.isEmpty()) {
            throw new IllegalArgumentException("上传文件不能为空");
        }
        if (kind == null || !List.of("live2d", "vrm", "rvc").contains(kind)) {
            throw new IllegalArgumentException("不支持的模型类型");
        }
        String safeOwner = sanitize(owner);
        String safeName = (name == null || name.isBlank()) ? file.getOriginalFilename() : name.trim();
        String stored = UUID.randomUUID().toString().replace("-", "") + "-" + sanitize(file.getOriginalFilename());
        Path dir = uploadRoot.resolve(safeOwner);
        Files.createDirectories(dir);
        Path target = dir.resolve(stored);
        file.transferTo(target);

        CloudModel model = new CloudModel(
                safeOwner,
                kind,
                safeName,
                file.getOriginalFilename(),
                stored,
                file.getSize()
        );
        repository.save(model);
        return toResponse(model);
    }

    public List<CloudModelResponse> list(String owner) {
        return repository.findByOwnerOrderByCreatedAtDesc(sanitize(owner)).stream()
                .map(this::toResponse)
                .toList();
    }

    public CloudModel get(String owner, Long id) {
        return repository.findByIdAndOwner(id, sanitize(owner))
                .orElseThrow(() -> new IllegalArgumentException("云模型不存在"));
    }

    public Path pathOf(CloudModel model) {
        return uploadRoot.resolve(sanitize(model.getOwner())).resolve(model.getStoredFilename());
    }

    public void delete(String owner, Long id) throws IOException {
        CloudModel model = get(owner, id);
        Files.deleteIfExists(pathOf(model));
        repository.delete(model);
    }

    private CloudModelResponse toResponse(CloudModel model) {
        return new CloudModelResponse(
                model.getId(),
                model.getOwner(),
                model.getKind(),
                model.getName(),
                model.getOriginalFilename(),
                model.getSize(),
                model.getCreatedAt().toString()
        );
    }

    private String sanitize(String value) {
        if (value == null) {
            return "default";
        }
        String cleaned = value.trim().replaceAll("[^a-zA-Z0-9_\\-\\u4e00-\\u9fa5]", "_");
        return cleaned.isBlank() ? "default" : cleaned;
    }
}
